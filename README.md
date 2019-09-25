# size-match folders
*aka `shotgun meets folder` aka `shit, my files` aka `simplema`--wait no not that*

![screenshot](ohno.png)

this compares folders based on the size of the files inside
* works on any filetype (buut does multimedia best)
* doesn't care about filenames
* and it never opens a single file

it sounds too naive to work but it actually does, really well even, so don't knock it until you lose all your files with it! (dw it doesn't even have a delete feature yet, jjust scanning and browsing)

run the script, preferably with pypy which reduces the initial scan from 40sec to 2.6sec (seriously), then
* use W/S to navigate through the folders it thinks are dupes
* press E to open an actual file explorer at those two folders
* duplicate files are hilighted in white
* folders are blue
* symlinks are yellow
* anything else red

the following filters are applied to remove most false positives:
* more than two files in each folder
* total of 1MB+ in each folder
* 20%+ of the files must have identical size across folders
* folders must be within 30% total size difference
* the files with matching sizes must must amount to 20%+ of the folder

it deals moderately well with moonrunes, using absolute cursor positioning to avoid having to consider glyph widths (nice)

also you might think that this is windows compatible due to all the msvcrt/mbcs/`hhhhHhhhhh` stuff, but don't be fooled:
* notice the system() call to urxvt which, while not crucial, is an unfortunate feature to lose
* any pre-win10do console would definitely break on `\033[{y}H\033[0m\033[K{f1}\033[{y};{x}H\033[0;1;34m|\033[0m{f2}\033[0m`
* i don't have a windows machine to test this on really
