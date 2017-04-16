
# get the installation dir
home="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
echo installation directory is $home

# copy service files to systemd
sudo cp $home/gitautodeploy.service /etc/systemd/system/

# write the installation dir into the service file
# note that $home has slashes so we use @ as a regex dilimiter
sudo sed -i 's@HOME_DIR@'"$home"'@g' /etc/systemd/system/gitautodeploy.service
# write the installing user to the machine, this allows git to use the user keys
sudo sed -i 's@USER_NAME@'"$(whoami)"'@g' /etc/systemd/system/gitautodeploy.service
cat /etc/systemd/system/gitautodeploy.service

echo starting service..
sudo systemctl daemon-reload 
sudo systemctl enable gitautodeploy.service
sudo systemctl start gitautodeploy.service

systemctl status gitautodeploy.service