#!/usr/bin/env python
""" Runs as an HTTP server and processes GIT HOOK requests """

import logging
import logging.handlers
import json
import sys
import os
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from subprocess import call
import argparse

__version__ = '0.2'
DEFAULT_CONFIG_FILEPATH = './GitAutoDeploy.conf.json'

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

LOGGER.addHandler(logging.handlers.SysLogHandler())

def fetch(path):
    """ executes fetch on a git repo """
    LOGGER.info('Post push request received, Updating %s', path)
    call(['cd "' + path + '" && git fetch'], shell=True)



class GitAutoDeploy(BaseHTTPRequestHandler):
    """ Server class, used to parse HTTP git hook requests """
    config = None
    quiet = False
    daemon = False

    def __init__(self, *args, **kwargs):
        self.event = None
        self.branch = None
        self.urls = None
        BaseHTTPRequestHandler.__init__(self, *args, **kwargs)

    @classmethod
    def init_config(cls, path):
        """ reads and parses config file """
        try:
            config_string = open(path).read()
        except EnvironmentError as ex:
            LOGGER.error('Could not load %s file, error: %s', path, ex)
            sys.exit()

        try:
            cls.config = json.loads(config_string)
        except ValueError as ex:
            LOGGER.error(' %s file is not valid json, error: %s', path, ex)
            sys.exit()

    # pylint: disable=C0103
    def do_POST(self):
        """ Handles HTTP POST requests """
        is_valid = False

        agent = self.headers.getheader("User-Agent")

        # print User-Agent, helps to diagnose, bitbucket should be
        # "Bitbucket-Webhooks/2.0"
        if not self.quiet:
            LOGGER.info("User Agent is: %s", agent)

        if agent == "Bitbucket-Webhooks/2.0":
            is_valid = self.processBitBucketRequest()
        else:
            is_valid = self.processGithubRequest()

        if is_valid:
            LOGGER.info('git hook request processed')
        else:
            LOGGER.error('could not process git hook request')

        for url in self.urls:
            paths = self.getMatchingPaths(url)
            for path in paths:
                fetch(path)
                self.deploy(path)

    def processGithubRequest(self):
        """ For Github git hook requests """
        self.event = self.headers.getheader('X-Github-Event')
        LOGGER.info("Recieved event %s", self.event)

        if self.event == 'ping':
            LOGGER.info('Ping event received')
            self.respond(204)
            return False
        if self.event != 'push':
            LOGGER.error('We only handle ping and push events')
            self.respond(304)
            return False

        self.respond(204)

        length = int(self.headers.getheader('content-length'))
        body = self.rfile.read(length)
        payload = json.loads(body)
        self.branch = payload['ref']
        self.urls = [payload['repository']['url']]
        return True

    def processBitBucketRequest(self):
        """ For bitbucket specific git hook requests """
        self.event = self.headers.getheader('X-Event-Key')
        LOGGER.info("Recieved event %s", self.event)

        if self.event != 'repo:push':
            LOGGER.wanr('We only handle ping and push events')
            self.respond(304)
            return False

        length = int(self.headers.getheader('content-length'))
        body = self.rfile.read(length)
        self.respond(204)
        payload = json.loads(body)
        self.branch = payload['push']['changes'][0]['new']['name']
        self.urls = [payload['repository']['links']['html']['href']]

        return True

    @classmethod
    def getMatchingPaths(cls, repoUrl):
        """ finds which repo was triggered in the git hook request """
        res = []
        for repository in cls.config['repositories']:
            if repository['url'] == repoUrl:
                res.append(repository['path'])
        return res

    def respond(self, code):
        """ sends HTTP response """
        self.send_response(code)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()


    def deploy(self, path):
        """ executes deploy script on a git repo, if the pushed branch matches the target branch"""
        for repository in GitAutoDeploy.config['repositories']:
            if repository['path'] == path:
                if repository.get('deploy'):
                    restrict_branch = repository.get('branch')
                    # deploy only if the specified branch in config matches the pushed branch
                    # or if we have no branch specified in config
                    if restrict_branch is None or restrict_branch == self.branch:
                        LOGGER.info('Executing deploy command')
                        call(['cd "' + path + '" && ' +
                              repository.get('deploy')], shell=True)
                    else:
                        LOGGER.warn(
                            'Push to different branch (%s != %s), not deploying',
                            restrict_branch, self.branch)

                return True
        return False

    @classmethod
    def validate(cls):
        """ validate that repos exist and are really bound to git repos """
        for repository in cls.config['repositories']:
            if not os.path.isdir(repository['path']):
                LOGGER.error('Git Repo at ' + repository['path'] + ' not found')
                return False
            # Check for a repository with a local or a remote GIT_WORK_DIR
            if not os.path.isdir(os.path.join(repository['path'], '.git')) \
               and not os.path.isdir(os.path.join(repository['path'], 'objects')):
                LOGGER.error('Directory ' + repository['path'] + ' is not a Git repository')
                return False
        return True

    @classmethod
    def test(cls, hostname):
        """ not implemented yet, supposed to send a dummy git hook request to the test server"""
        pass


def get_args():
    """ parses command line args """
    parser = argparse.ArgumentParser(description='Github Autodeploy Service')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='disable status reporting')
    parser.add_argument('-d', '--daemon-mode',
                        action='store_true', help='run this script as a daemon')
    parser.add_argument('-t', '--test', help='send a test hook event to host')
    parser.add_argument('-c', '--config', default=DEFAULT_CONFIG_FILEPATH,
                        help='provide an alternative path for the config file used')

    return parser.parse_args()


def main():
    """ main! """
    server = None
    LOGGER.info('Github Autodeploy Service v' + __version__ + ' started')
    console_handler = logging.StreamHandler()
    LOGGER.addHandler(console_handler)
    try:
        args = get_args()

        GitAutoDeploy.quiet = args.quiet or args.daemon_mode
        GitAutoDeploy.daemon = args.daemon_mode
        if GitAutoDeploy.quiet:
            LOGGER.removeHandler(console_handler)
        GitAutoDeploy.init_config(args.config)

        if not GitAutoDeploy.validate():
            sys.exit()

        if args.test:
            GitAutoDeploy.test(args.test)

        if GitAutoDeploy.daemon:
            LOGGER.info("Forking")
            pid = os.fork()
            if pid:
                # we are in the parent
                try:
                    pid_file = open('/tmp/gitdeploy.pid', 'w')
                    pid_file.write(str(pid))
                    pid_file.close()
                except EnvironmentError as ex:
                    LOGGER.error("Failed to write to PID file, %s", ex)
                    sys.exit()
                LOGGER.info("main proccess exiting")
                sys.exit()
            LOGGER.info("fork resuming")
            os.setsid()

        if GitAutoDeploy.daemon:
            LOGGER.info('Github Autodeploy Service v' +
                        __version__ + ' started in daemon mode')

        server = HTTPServer(('', GitAutoDeploy.config['port']), GitAutoDeploy)
        LOGGER.info("listening on port %d", GitAutoDeploy.config['port'])
        server.serve_forever()
    # pylint: disable=W0703
    except (EnvironmentError, KeyboardInterrupt, Exception) as ex:
        LOGGER.error(ex)
    finally:
        if server:
            server.socket.close()

        LOGGER.info("quitting..")


if __name__ == '__main__':
    main()
