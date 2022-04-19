## Docker

To run `lndmanage` from a docker container:

```sh
# you should first review ./home/config_template.ini
# note that paths are relevant to situation inside docker and we run under root
# so $HOME directory is /root

# build the container
./build.sh 

# if you have local lnd node on host machine, point LND_HOME to your actual lnd directory:
export LND_HOME=~/.lnd

# or alternatively if you have remote lnd node, specify paths to auth files explicitly:
# export TLS_CERT_FILE=/path/to/tls.cert
# export ADMIN_MACAROON_FILE=/path/to/admin.macaroon  
# export LND_GRPC_HOST=<remoteip>:10009

# look into _settings.sh for more details on container configuration

# run lndmanage from the container: 
./lndmanage.sh status

# lndmanage cache will be mapped to host folder at ./_volumes/lndmanage-cache
```

To start from scratch:
```sh
./clean.sh
./build.sh --no-cache
```
