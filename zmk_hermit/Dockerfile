ARG ZMK_IMAGE=zmkfirmware/zmk-build-arm
FROM $ZMK_IMAGE

# setup user so we don't have to run as root
ARG USER=zmkuser
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID -o $USER
RUN useradd -m -u $UID -g $GID -o -s /bin/bash $USER
USER $USER
WORKDIR /home/$USER

# get ZMK
ARG ZMK_REPO=https://github.com/zmkfirmware/zmk.git
RUN git clone $ZMK_REPO
WORKDIR zmk

# initialize build environment
RUN west init -l app
RUN west update
RUN west zephyr-export

# set compilation script as entry point
COPY helper.py .
ENTRYPOINT ["python3", "helper.py"]