 # deploys the GitDeploy client to a remote server
   rsync -avr --exclude ".git" -e "ssh -i ~/.ssh/KEY.pem" . USER@HOST:/home/USER/gitdeploy
   