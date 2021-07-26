# ZMK hermit

Compile out-of-tree ZMK keyboards.

## Method

1. setup a docker container with external shield/board directory and (optionally) keymap file mounted appropriately in container's `zmk-config`
2. run a helper script in container to run build command(s) and rename output

Basically a local equivalent of the Github workflow but based on command-line rather that files/directory structure.


## Example

```bash
zmk-hermit ~/my-split-kb/zmk-shield nice_nano_v2 --keymap ~/my-keymaps/qwerty1.keymap --into ~/zmk-firmware
```
will output (slightly truncated):
```
guessed shield name `my_split_kb` from `/home/user/my-split-kb/zmk-shield`
building image...
┎─
┃ Successfully built f69e3032e11a
┃ Successfully tagged zmk-hermit:latest
┖─
running container...
  with `/home/user/zmk-firmware` as `/artefacts` (rw)
       `/home/user/my-split-kb/zmk-shield` as `/zmk-config/boards/shields/my_split_kb` (ro)
       `/home/user/my-keymaps/qwerty1.keymap` as `/zmk-config/my_split_kb.keymap` (ro)

`west build --pristine -s app -b nice_nano_v2 -- -DSHIELD=my_split_kb_left -DZMK_CONFIG=/zmk-config`
┎─
┃ -- west build: generating a build system
┃ -- Adding ZMK config directory as board root: /zmk-config
┃ -- ZMK Config directory: /zmk-config
┃ -- Board: nice_nano_v2, /home/zmkuser/zmk/app/boards/arm/nice_nano, my_split_kb_left, my_split_kb
┃ -- Using keymap file: /zmk-config/my_split_kb.keymap
...
┃ [1/274] Preparing syscall dependency handling
┃ [274/274] Linking C executable zephyr/zmk.elf
┃ Memory region         Used Size  Region Size  %age Used
┃            FLASH:      181884 B       792 KB     22.43%
┃             SRAM:       50967 B       256 KB     19.44%
┃         IDT_LIST:          0 GB         2 KB      0.00%
┃ Converted to uf2, output size: 364032, start address: 0x26000
┃ Wrote 364032 bytes to /home/zmkuser/zmk/build/zephyr/zmk.uf2
┖─
copied `build/zephyr/zmk.uf2` to `/artefacts/my_split_kb-nice_nano_v2-qwerty1.left.uf2`
`west build --pristine -s app -b nice_nano_v2 -- -DSHIELD=my_split_kb_right -DZMK_CONFIG=/zmk-config`
┎─
┃ -- west build: making build dir /home/zmkuser/zmk/build pristine
┃ -- west build: generating a build system
┃ -- Adding ZMK config directory as board root: /zmk-config
┃ -- ZMK Config directory: /zmk-config
┃ -- Board: nice_nano_v2, /home/zmkuser/zmk/app/boards/arm/nice_nano, my_split_kb_right, my_split_kb
┃ -- Using keymap file: /zmk-config/my_split_kb.keymap
...
┃ [1/253] Preparing syscall dependency handling
┃ [253/253] Linking C executable zephyr/zmk.elf
┃ Memory region         Used Size  Region Size  %age Used
┃            FLASH:      150791 B       792 KB     18.59%
┃             SRAM:       38343 B       256 KB     14.63%
┃         IDT_LIST:          0 GB         2 KB      0.00%
┃ Converted to uf2, output size: 302080, start address: 0x26000
┃ Wrote 302080 bytes to /home/zmkuser/zmk/build/zephyr/zmk.uf2
┖─
copied `build/zephyr/zmk.uf2` to `/artefacts/my_split_kb-nice_nano_v2-qwerty1.right.uf2`
removing container...
done.
```
write the compiled files as `~/zmk-firmware/my_split_kb-nice_nano_v2-qwerty1.left.uf2` and `~/zmk-firmware/my_split_kb-nice_nano_v2-qwerty1.right.uf2`.



## Disclaimer

This is a personal work-in-progress and does not (and most probably will not) cover all of the ZMK use-cases.
