#!/bin/bash

cat >/dev/null <<EOF
 \033[47;48;5;28;1mgreen folders\033[0m are 100% dupes and safe to delete
\033[33myellow folders\033[0m contain some dupes and so does all subfolders
\033[35mpurple folders\033[0m have subfolders which are not dupes
   \033[31mred folders\033[0m contain only unique data
  \033[36mblue folders\033[0m should not appear, let me know if you see one
EOF

rm -rf /dev/shm/smf
mkdir -p /dev/shm/smf
cd /dev/shm/smf

gf() { s=1${1}0000000; s=$((s+$2)); shift 2; for f in "$@"; do s=$((s+1)); mkdir -p ${f%/*}; truncate -s $s $f; done; }

gf 1 0 g1/{f1,f2,f3}
gf 1 0 g2/{f1,f2,f3}
gf 1 0 g2b/{f1,f2,f3}; gf 1 0 g2b/f2; printf h >> g2b/f2
gf 1 0 y1/{f1,f2,f3,f4}
for n in {1..3}; do gf 2 0 gp1/gc$n/{f1,f2,f3}; done
for n in {1..3}; do gf 2 0 gp2/gc$n/{f1,f2,f3}; done
for n in {1..3}; do gf 2 0 pp2/gc$n/{f1,f2,f3}; done; mkdir pp2/gc3/empty
for n in {1..2}; do gf 2 0 yp1/gc$n/{f1,f2,f3}; done; gf 2 0 yp1/yc1/{f1,f2,f3,f4};
for n in {1..2}; do gf 2 0 pp1/gc$n/{f1,f2,f3}; done; gf 2 9 pp1/rc1/{f1,f2,f3,f4};

#mkdir -p g{1,2} y1 gp{1,2}/gc{1,2,3} yp{1,2}/gc{1,2,3} yp2/yc1
#truncate -s 110000001 1.1.1

#gf 1 0 g1/{f1,f2,f3}
#gf 1 0 g2/{f1,f2,f3,f4}
#gf 1 1 g3/{f2,f3,f4}
