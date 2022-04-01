# ZMK hermit

Compile out-of-tree ZMK keyboards.

## Method

1. setup a docker container with external shield/board directory and (optionally) keymap file mounted appropriately in container's `zmk-config`
2. run a helper script in container to run build command(s) and rename output

Basically a local equivalent of the Github workflow but based on command-line rather that files/directory structure.


## Example

```bash
zmk-hermit ~/my-split-kb/zmk-shield/ nice_nano_v2 --keymap ~/my-keymaps/qwerty1.keymap --zmk-src ~/my-zmk-fork --into /tmp -v
```
will output (slightly truncated):
```
guessed shield name `my_split_kb` from `/home/user/my-split-kb/zmk-shield`
building image...
Successfully built c093ea715a57
Successfully tagged zmk-hermit:latest
running container...
  using `/tmp` as `/artefacts` (rw)
  using `/home/user/my-split-kb/zmk-shield` as `/zmk-config/boards/shields/my_split_kb` (rw)
  using `/home/user/my-keymaps/qwerty1.keymap` as `/zmk-config/my_split_kb.keymap` (ro)
  using `/home/user/my-zmk-fork` as `/home/zmkuser/zmk` (ro)
  with args: python3 build.py my_split_kb nice_nano_v2 --name my_split_kb-nice_nano_v2-qwerty1 -f uf2 --zmk /home/zmkuser/zmk --config /zmk-config --into /artefacts --build /tmp/zmk-build --verbose
╭─────┄┈
│ found shield `my_split_kb` at `/zmk-config/boards/shields/my_split_kb`
│ guessing shield is split
│ run `west build -b nice_nano_v2 --pristine auto -d /tmp/zmk-build/my_split_kb_left-nice_nano_v2 -- -DSHIELD=my_split_kb_left -DZMK_CONFIG=/zmk-config`
│ -- west build: generating a build system
│ -- Adding ZMK config directory as board root: /zmk-config
│ -- ZMK Config directory: /zmk-config
│ -- Board: nice_nano_v2, /home/zmkuser/zmk/app/boards/arm/nice_nano, my_split_kb_left, my_split_kb
│ -- Using keymap file: /zmk-config/my_split_kb.keymap
...
│ -- Build files have been written to: /tmp/zmk-build/my_split_kb_left-nice_nano_v2
│ -- west build: building application
│ [1/260] Preparing syscall dependency handling
│ 
│ [260/260] Linking C executable zephyr/zmk.elf
│ Memory region         Used Size  Region Size  %age Used
│            FLASH:      152701 B       792 KB     18.83%
│             SRAM:       38495 B       256 KB     14.68%
│         IDT_LIST:          0 GB         2 KB      0.00%
│ Converted to uf2, output size: 305664, start address: 0x26000
│ Wrote 305664 bytes to /tmp/zmk-build/my_split_kb_left-nice_nano_v2/zephyr/zmk.uf2
│ copy `/tmp/zmk-build/my_split_kb_left-nice_nano_v2/zephyr/zmk.uf2` to `/artefacts/my_split_kb-nice_nano_v2-qwerty1.left.uf2`
│ run `west build -b nice_nano_v2 --pristine auto -d /tmp/zmk-build/my_split_kb_right-nice_nano_v2 -- -DSHIELD=my_split_kb_right -DZMK_CONFIG=/zmk-config`
│ -- west build: generating a build system
│ -- Adding ZMK config directory as board root: /zmk-config
│ -- ZMK Config directory: /zmk-config
│ -- Board: nice_nano_v2, /home/zmkuser/zmk/app/boards/arm/nice_nano, my_split_kb_right, my_split_kb
│ -- Using keymap file: /zmk-config/my_split_kb.keymap
...
│ -- Build files have been written to: /tmp/zmk-build/my_split_kb_right-nice_nano_v2
│ -- west build: building application
│ [1/283] Preparing syscall dependency handling
│ 
│ [283/283] Linking C executable zephyr/zmk.elf
│ Memory region         Used Size  Region Size  %age Used
│            FLASH:      201644 B       792 KB     24.86%
│             SRAM:       60035 B       256 KB     22.90%
│         IDT_LIST:          0 GB         2 KB      0.00%
│ Converted to uf2, output size: 403456, start address: 0x26000
│ Wrote 403456 bytes to /tmp/zmk-build/my_split_kb_right-nice_nano_v2/zephyr/zmk.uf2
│ copy `/tmp/zmk-build/my_split_kb_right-nice_nano_v2/zephyr/zmk.uf2` to `/artefacts/my_split_kb-nice_nano_v2-qwerty1.right.uf2`
╰─────┄┈
removed container.
retrieved `/tmp/my_split_kb-nice_nano_v2-qwerty1.right.uf2`
retrieved `/tmp/my_split_kb-nice_nano_v2-qwerty1.left.uf2`
```
The compiled files `my_split_kb-nice_nano_v2-qwerty1.left.uf2` and `my_split_kb-nice_nano_v2-qwerty1.right.uf2` are copied into `/tmp`.



## Disclaimer

This is a personal work-in-progress and does not (and most probably will not) cover all of the ZMK use-cases.
