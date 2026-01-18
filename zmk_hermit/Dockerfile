ARG ZMK_IMAGE
FROM $ZMK_IMAGE

RUN apt-get update && apt-get install -y imagemagick

# setup user so we don't have to run as root
ARG USER=zmkuser
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID -o $USER
RUN useradd -m -u $UID -g $GID -o -s /bin/bash $USER
USER $USER
WORKDIR /home/$USER
