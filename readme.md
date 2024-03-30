# ZMK hermit

Compile ZMK firmware with out-of-tree boards, shields, keymaps, or behaviors; inside a Docker container.

## Method

1. setup a docker container with external shield/board directory and (optionally) keymap file mounted appropriately in container's `zmk-config`
2. run a helper script in container to run build command(s) and rename output

Basically a local equivalent of the Github workflow but based on command-line rather that files/directory structure.

## `zmk_build`

This Python package contains utility functions to analyze ZMK shield and board directories and generate `west build` commands, as well as a command line tool to run them.

For example:

```sh
python -m zmk_build
  corne  # shield
  nice_nano_v2  # board
  --into ~/  # copy compiled firmware to home directory
  --left-only  # only do left side
  --with-logging  # activate usb logging
  --with-kb-name "corne2"  # set device name
  --dry-run  # don't actually do it, just print for the readme :)
```
```
found shield `corne` at `app/boards/shields/corne`
guessing shield is split (`left`, `right`)
would run `west build -b nice_nano_v2 --pristine auto -s app -d /tmp/zmk-build/corne_left-nice_nano_v2 -- -DSHIELD=corne_left -DCONFIG_KERNEL_BIN_NAME=\"corne-nice_nano_v2.left\" -DCONFIG_ZMK_USB_LOGGING=y -DCONFIG_ZMK_KEYBOARD_NAME=\"debug_corne\" -Wno-dev`
would copy `/tmp/zmk-build/corne_left-nice_nano_v2/zephyr/corne-nice_nano_v2.left.uf2` to `~/corne-nice_nano_v2[logging=y,name=debug_corne].left.uf2`
not building `right` side (`left` only)
```


## `zmk_hermit`

This Python package contains provides a command line tool to set up a Docker container in which to run `zmk_build`.
It takes care of mounting out-of-tree boards, shields, and behaviors appropriately in the `zmk-config` folder inside the container before running the build, as well as retrieving the artefacts afterwards.

```sh
python -m zmk_hermit
  ~/my-split-kb/zmk-shield/  # out-of-tree shield
  nice_nano_v2  # board
  --keymap ~/my-keymaps/qwerty1.keymap  # out-of-tree keymap
  --into ~/  # copy compiled firmware to home directory
```


## Disclaimer

This is a personal work-in-progress and does not (and most probably will not) cover all of the ZMK use-cases.
