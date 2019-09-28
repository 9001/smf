#!/usr/bin/env python3
# coding: utf-8
from __future__ import print_function, unicode_literals

import re
import os
import sys
import stat
import time
import math
import gzip
import struct
import tempfile
import platform
import threading
import subprocess as sp
from datetime import datetime


"""smf.py: file undupe by sizematching files in folders"""
__version__   = "0.3"
__author__    = "ed <smf@ocv.me>"
__credits__   = ["stackoverflow.com"]
__license__   = "MIT"
__copyright__ = 2019


FS_ENCODING = sys.getfilesystemencoding()

ENC_FILTER = 'surrogateescape'
if sys.version_info[0] == 2:
	# drop mojibake support for py2 (bytestrings everywhere is a pain)
	ENC_FILTER = 'replace'


if sys.platform.startswith('linux') \
or sys.platform in ['darwin', 'cygwin']:
	VT100 = True
	TERM_ENCODING = sys.stdout.encoding

	import tty, termios
	def getch():
		ch = 0
		fd = sys.stdin.fileno()
		old_cfg = termios.tcgetattr(fd)
		tmp_cfg = termios.tcgetattr(fd)
		tmp_cfg[3] &= ~termios.ICANON & ~termios.ECHO
		try:
			# tty.setraw(fd)
			termios.tcsetattr(fd, termios.TCSADRAIN, tmp_cfg)
			ch = sys.stdin.read(1)
			sys.stdout.flush()
		finally:
			termios.tcsetattr(fd, termios.TCSADRAIN, old_cfg)
		return ch

	import fcntl, termios, os
	def termsize():
		env = os.environ
		def ioctl_GWINSZ(fd):
			try:
				sz = fcntl.ioctl(fd, termios.TIOCGWINSZ, b'\x00'*8)
				return struct.unpack('HHHH', sz)[:2]
			except:
				print('std fd {} failed'.format(fd))
				return
		
		cr = ioctl_GWINSZ(0) or ioctl_GWINSZ(1) or ioctl_GWINSZ(2)
		if not cr:
			try:
				fd = os.open(os.ctermid(), os.O_RDONLY)
				cr = ioctl_GWINSZ(fd)
				os.close(fd)
			except:
				print('term fd {} failed'.format(fd))
				pass
		
		if not cr:
			try:
				cr = [env['LINES'], env['COLUMNS']]
			except:
				print('env failed')
				cr = [25, 80]
		
		return int(cr[1]), int(cr[0])


elif sys.platform == 'win32':
	VT100 = False
	TERM_ENCODING = 'cp65001'
	PYPY = platform.python_implementation() == 'PyPy'

	if sys.version_info[0] == 2:
		TERM_ENCODING = 'cp1252'  # cp932 if weeb
		FS_ENCODING = 'mbcs'  # close enough?
	elif PYPY:
		TERM_ENCODING = 'utf-8'  # pypy bug: 65001 not impl
		FS_ENCODING = 'utf-8'  # pypy bug: thinks we are mbcs

	import msvcrt
	def getch():
		while msvcrt.kbhit():
			msvcrt.getch()
		
		rv = msvcrt.getch()
		try:
			return rv.decode(TERM_ENCODING, 'replace')
		except:
			return rv  # pypy bug: getch is str()

	from ctypes import windll, create_string_buffer
	def termsize_native():
		ret = None
		try:
			# fd_stdin, fd_stdout, fd_stderr = [-10, -11, -12]
			h = windll.kernel32.GetStdHandle(-12)
			csbi = create_string_buffer(22)
			ret = windll.kernel32.GetConsoleScreenBufferInfo(h, csbi)
		except:
			return None
		
		if not ret:
			return None
			
		(bufx, bufy, curx, cury, wattr,
		 left, top, right, bottom, maxx, maxy) = \
			struct.unpack('hhhhHhhhhhh', csbi.raw)
		
		return [right - left + 1, bottom - top + 1]
	
	def termsize_ncurses():
		try:
			return [
				int(sp.check_output(['tput', 'cols'])),
				int(sp.check_output(['tput', 'lines'])),
			]
		except:
			return None
	
	def termsize():
		ret = termsize_native() or termsize_ncurses()
		if ret:
			return ret
		
		raise Exception('powershell is not supported; use cmd on win10 or use cygwin\n'*5)

	from ctypes import Structure, c_short, c_char_p
	class COORD(Structure):
		pass

	COORD._fields_ = [("X", c_short), ("Y", c_short)]

	re_pos = re.compile('\033\\[([0-9]+)?(;[0-9]+)?H')
	re_ansi = re.compile('\033\\[[^a-zA-Z\033]*[a-zA-Z]')
	re_color = re.compile('\033\\[[0-9;]*m')
	re_other_ansi = re.compile('\033\\[[^a-zA-Z\033]*[a-lnzA-GI-Z]')

	wcp = TERM_ENCODING
	if wcp.startswith('cp'):
		wcp = wcp[2:]

	v = sp.check_output('chcp', shell=True).decode('utf-8')
	if ' {}'.format(wcp) not in v and not PYPY:
		_ = os.system('chcp ' + wcp)  # fix moonrunes
		msg = '\n\n\n\n  your  codepage  was  wrong\n\n  dont worry, i just fixed it\n\n    please  run  me  again\n\n\n\n             -- smf, 2019\n\n\n'
		try:
			sys.stdout.buffer.write(msg.encode('ascii'))
		except:
			sys.stdout.write(msg.encode('ascii'))

		exit()

	_ = os.system('cls')  # somehow enables the vt100 interpreter??
	
	print('fsys:', FS_ENCODING)
	print('term:', TERM_ENCODING)

	def wprint(txt):
		_ = os.system('cls')  # ensure vt100 is still good
		#txt = re_other_ansi.sub('', txt)
		
		h = windll.kernel32.GetStdHandle(-11)
		ptr = 0
		for m in re_pos.finditer(txt):
			#print(txt[ptr:m.start()], end='')
			c = txt[ptr:m.start()].encode(TERM_ENCODING, 'replace')
			windll.kernel32.WriteConsoleA(h, c_char_p(c), len(c), None, None)
			ptr = m.end()
			y, x = m.groups()
			y = int(y) if y else 1
			x = int(x[1:]) if x else 1
			windll.kernel32.SetConsoleCursorPosition(h, COORD(x-1, y-1))

		#print(txt[ptr:], end='')
		#windll.kernel32.SetConsoleCursorPosition(h, COORD(0, 0))
		#print()
		#sys.stdout.flush()
		c = txt[ptr:].encode(TERM_ENCODING, 'replace')
		windll.kernel32.WriteConsoleA(h, c_char_p(c), len(c), None, None)

else:
	raise Exception('unsupported platform: {}'.format(sys.platform))


########################################################################
########################################################################


def fsenc(path):
	return path.encode(FS_ENCODING, ENC_FILTER)


def fsdec(path):
	return path.decode(FS_ENCODING, ENC_FILTER)


class Folder(object):
	"""
	the absolute path to a folder, and
	the size of each file directly within
	"""
	def __init__(self, path):
		self.path = path
		self.files = []
	
	def __str__(self):
		return '\033[36m{:6} \033[35m{:12}\033[0m {}'.format(
			len(self.files), sum(self.files), self.path)


class DiskWalker(object):
	def __init__(self, top):
		self.cur_top = top
		self.folders = []
		
		thr = threading.Thread(target=self.logger)
		thr.daemon = True
		thr.start()
		
		print('\n\033[32mentering\033[0m', top)
		self.dev_id = os.lstat(top).st_dev
		self.walk(top)
		self.cur_top = None
		print('\033[32mleaving\033[0m', top)

	def logger(self):
		last_top = None
		while True:
			time.sleep(0.05)
			if not self.cur_top:
				break
			
			if last_top == self.cur_top:
				continue
			
			last_top = self.cur_top
			print('\033[36mreading\033[0m', self.cur_top)
	
	def walk(self, top):
		self.cur_top = top
		dev_id = self.dev_id
		folder = Folder(top)
		btop = fsenc(top)
		for bfn in sorted(os.listdir(btop)):
			bpath = os.path.join(btop, bfn)
			try:
				sr = os.lstat(bpath)
			except:
				print('\033[1;31maccess denied:\033[0m', fsdec(bpath))
				continue
			
			mode = sr.st_mode
			
			if stat.S_ISLNK(mode):
				continue
			
			elif sr.st_dev != dev_id:
				print('\033[35mskipping mountpoint:\033[0m', fsdec(bpath))
			
			elif stat.S_ISDIR(mode):
				try:
					self.walk(fsdec(bpath))
				except KeyboardInterrupt:
					raise
				except:
					print('\033[1;31maccess denied:\033[0m', fsdec(bpath))

			elif stat.S_ISREG(mode) and sr.st_size > 0:
				folder.files.append(sr.st_size)

		if folder.files \
		and sum(folder.files) > 1*1024*1024 \
		and len(folder.files) > 2:
			self.folders.append(folder)


def gen_dupe_map(roots):
	print("\nscanning disk...")
	
	t0 = time.time()
	folders = []
	for root in roots:
		dw = DiskWalker(root)
		folders.extend(dw.folders)
	
	print("\ngenerating dupemap (hope you're using pypy w)")

	# compare each unique permutation of [Folder,Folder]
	t1 = time.time()
	nth = 0
	dupes = []
	remains = len(folders)
	for folder1 in folders:
		#print(str(folder))
		nth += 1
		remains -= 1
		if nth % 10 == 0:
			print('{} / {}'.format(nth, remains))
		
		for folder2 in folders[nth:]:
			# hits = each file size that matched,
			# rhs = the remaining files in folder2 to check
			# (to deal w/ multiple files of same size in one folder)
			hits = []
			rhs = folder2.files[:]
			for sz in folder1.files:
				if sz in rhs:
					hits.append(sz)
					rhs.remove(sz)
			
			score = (len(hits) * 2.0) / (
				len(folder1.files) + len(folder2.files))
			
			# must be 20% or more files with identical size
			if score < 0.2:
				continue
			
			# total disk consumption must be <= 30% different
			a = sum(folder1.files)
			b = sum(folder2.files)
			if min(a,b) * 1.0 / max(a,b) < 0.7:
				continue
			
			# matched files must amount to >= 20% of bytes
			if sum(hits) < a * 0.2 \
			and sum(hits) < b * 0.2:
				continue
			
			dupes.append([score, folder1, folder2])

	t2 = time.time()
	return dupes, [t1-t0, t2-t1]


def save_dupe_map(cache_path, dupes):
	with gzip.open(cache_path, 'wb') as f:
		seen_folders = {}
		n = 0
		
		# serialize folders that contain dupes
		for _, fld1, fld2 in dupes:
			for fld in [fld1, fld2]:
				if fld not in seen_folders:
					txt = 'p {}\nf {}\n'.format(fld.path,
						' '.join(str(x) for x in fld.files))
					
					f.write(txt.encode('utf-8', ENC_FILTER))
					seen_folders[fld] = n
					n += 1
		
		# serialize dupe info
		for score, fld1, fld2 in dupes:
			f.write('d {} {} {}\n'.format(
				int(score*1000),
				seen_folders[fld1],
				seen_folders[fld2]).encode('utf-8'))
		
		f.write(b'eof\n')


def load_dupe_map(cache_path):
	folders = []
	dupes = []
	with gzip.open(cache_path, 'rb') as f:
		while True:
			ln = f.readline()[:-1].decode('utf-8', ENC_FILTER)
			if ln.startswith('p '):
				ln2 = f.readline()[:-1].decode('utf-8')
				if not ln2.startswith('f '):
					raise Exception('non-f after p')
				
				folder = Folder(ln[2:])
				for sz in ln2[2:].split(' '):
					folder.files.append(int(sz))
				
				folders.append(folder)
				continue
			
			if ln.startswith('d '):
				score, i1, i2 = [int(x) for x in ln[2:].split(' ')]
				dupes.append([score/1000., folders[i1], folders[i2]])
				continue
			
			if ln == 'eof':
				break
			
			raise Exception('unexpected line: {}'.format(ln))

	return dupes


def colorize_score(score):
	if score == "xxx":
		return '0;37', score
	
	if score < 0.2:
		c = '1;30'
	elif score < 0.35:
		c = '0;31'
	elif score < 0.5:
		c = '0;36'
	elif score < 0.7:
		c = '0;33'
	elif score < 0.9:
		c = '1;32'
	elif score <= 1:
		c = '1;37;44;48;5;28'
	else:
		c = '1;37;41'
	
	return c, int(score*100)


def dump_summary(dupes):
	# keep track of the 1st folder in the pair,
	# print it as a header for all the folders it matched against
	last_lhs = None
	for score, lhs, rhs in dupes:
		ln = lhs.path
		rn = rhs.path
		if last_lhs != ln:
			last_lhs = ln
			print('\n\033[1;37m{:5}{}\033[0m'.format('', ln))
		
		cs, s = colorize_score(score)
		print('\033[{}m{:3d}%\033[0m {}'.format(cs, s, rn))


def read_folder(top):
	ret = []
	btop = fsenc(top)
	#top = fsenc(unitop)
	for bfn in sorted(os.listdir(btop)):
		bpath = os.path.join(btop, bfn)
		sr = os.lstat(bpath)
		mode = sr.st_mode
		fn = fsdec(bfn)
		
		if stat.S_ISREG(mode):
			ret.append([sr.st_size, sr.st_mtime, fn])
		else:
			n = -3
			if stat.S_ISLNK(mode):
				n = -2
			elif stat.S_ISDIR(mode):
				n = -1
			
			ret.append([n, n, fn])
	
	return ret


def draw_panel(panel_w, statlist, other_sizes):
	ret = []
	meta_len = 21
	fn_len = panel_w - (meta_len + 1)
	for sz, ts, fn in statlist:
		meta = ' ' * meta_len
		if sz >= 0:
			c = '0'
			if sz in other_sizes:
				other_sizes.remove(sz)
				c = '1;30;47'
			
			sz = str(sz).rjust(11)
			sz = '{}\033[36m{}\033[0m{}'.format(
				sz[:-6], sz[-6:-3], sz[-3:])

			ts = datetime.utcfromtimestamp(ts).strftime('%Y-%m%d')
			meta = '{} {}'.format(ts, sz)
		
		elif sz == -2:
			# symlink
			c = '0;33'
		
		elif sz == -1:
			# dir
			c = '0;36'
		
		else:
			# unhandled
			c = '1;31'
		
		ret.append('{} \033[{}m{}'.format(
			meta, c, fn[:fn_len].ljust(fn_len)))

	return ret


def termsafe(txt):
	try:
		return txt.encode(TERM_ENCODING, 'backslashreplace').decode(TERM_ENCODING)
	except:
		return txt.encode(TERM_ENCODING, 'replace').decode(TERM_ENCODING)


class FSDir(object):
	def __init__(self, path):
		self.path = path
		self.dirs = {}
		self.files = []
		self.smin = 9
		self.smax = -9
		self.scur = -9

	def build_until(self, dest, extra_levels=1):
		if extra_levels < 0 or (
			not dest.startswith(self.path) \
			and not self.path.startswith(dest)
		):
			raise Exception('\n[{}]  # self\n[{}]  # dest\n[{}]'.format(
				self.path, dest, extra_levels))
		
		if self.path.startswith(dest):
			extra_levels -= 1
		
		if self.files or self.dirs:
			if extra_levels > 0:
				dn = dest[len(self.path):].split('/', 1)[0]
				self.dirs[dn].build_until(dest, extra_levels)
			
			return
		
		bself = fsenc(self.path)
		for bfn in sorted(os.listdir(bself)):
			fn = fsdec(bfn)
			bpath = os.path.join(bself, bfn)
			path = os.path.join(self.path, fn)
			
			sr = os.lstat(bpath)
			mode = sr.st_mode

			if stat.S_ISREG(mode):
				self.files.append([sr.st_size, sr.st_mtime, fn])
			elif stat.S_ISLNK(mode):
				self.files.append([-2, -2, fn])
			elif stat.S_ISDIR(mode):
				path += '/'
				subdir = FSDir(path)
				self.dirs[fn] = subdir

				if dest.startswith(path) \
				or (path.startswith(dest) and extra_levels > 0):
					subdir.build_until(dest, extra_levels)
	
	def format(self, lv=0):
		scores = ''.join(['\033[{}m{:>3}%\033[0m '.format(x, y) for x, y in [
			colorize_score("xxx" if self.smin > 7 else self.smin),
			colorize_score("xxx" if self.smax < -7 else self.smax),
			colorize_score("xxx" if self.scur < -7 else self.scur)]])

		if self.smin == 1: cdir = '7;48;5;28;1' # purely dupes; green
		elif self.smax < -7: cdir = 1  # purely unique; red
		elif self.smin > 7: cdir = 5  # contains unique folders; purple
		elif self.smin > 0: cdir = 3  # purely folders with dupes; yellow
		else: cdir = 6  # wait what did i forget
		
		ret = '{scores} {pad}\033[0;3{cdir}m{path}\033[0m\n'.format(
			scores = scores,
			pad = '{}\033[1;3{}m|'.format(' ' * (lv * 2 - 1), lv%8) if lv else '',
			cdir = cdir,
			path = self.path)
		
		for _, p in sorted(self.dirs.items()):
			ret += p.format(lv + 1)
		
		if self.dirs and not ret.endswith('\n\n'):
			ret += '\n'
		
		return ret

	def dump_tree(self, lv=0):
		pad = '{}\033[1;3{}m|'.format(' ' * (lv * 2 - 1), lv%8) if lv else ''
		ret = '{}\033[0;36m{}\033[0m\n'.format(pad, self.path)
		
		for _, p in sorted(self.dirs.items()):
			ret += p.dump(lv + 1)
		
		for p in self.files:
			ret += '{}\033[0m{}\n'.format(pad, p[2])
		
		return ret


class TUI(object):
	def __init__(self, cur_path):
		self.gen_time = [0,0]
		self.cur_path = cur_path
		self.fs = None

	def set_dupes(self, dupes):
		self.dupes = dupes
		self.fs = None

	def tree(self):
		if not self.fs:
			print('\033[36mbuilding directory tree...\033[0m')
			self.fs = FSDir('/')
			for score, fld1, fld2 in self.dupes:
				for path in [fld1.path, fld2.path]:
					pathnodes = path.lstrip('/').split('/')
					fsnode = self.fs
					for pathnode in pathnodes:
						try:
							fsnode = fsnode.dirs[pathnode]
							if not fsnode.dirs and not fsnode.files:
								self.fs.build_until(path + '/')
						except:
							self.fs.build_until(path + '/')
							fsnode = fsnode.dirs[pathnode]
						
						fsnode.smin = min(fsnode.smin, score)
						fsnode.smax = max(fsnode.smax, score)
					
					fsnode.scur = max(fsnode.scur, score)
			
			# propagate unique folders up by resetting minimum score
			def foo1(node):
				have_unique = False
				for _, f in node.dirs.items():
					if foo1(f):
						have_unique = True
				
				if node.scur < 0:
					have_unique = True
				
				if have_unique:
					node.smin = 9
					return True

			foo1(self.fs)

			# noise filter: remove folders with no dupes at all
			def foo2(node, parent_has_dupes=False):
				drop = []
				for k, v in node.dirs.items():
					if v.smax < -7:
						drop.append(k)
				
				# leave one leaf to indicate unique data within
				i_have_dupes = node.scur > -7 or node.smax > -7
				if parent_has_dupes or i_have_dupes:
					drop = drop[1:]
				
				for k in drop:
					del node.dirs[k]
			
				for _, v in node.dirs.items():
					foo2(v, i_have_dupes)
			
			foo2(self.fs)
		
		tree = self.fs.format()

		# TODO gui
		header = '\033[0;1;40mmin% max% dir%\033[0m'
		print('\n' + header)
		print(termsafe(tree))
		#for ln in termsafe(tree).split('\n'):
		#	if '/m3-' in ln:
		#		print(ln)
		print(header)
		print("""
first column is xxx if there exists purely-unique folders below this point,
first column is numeric with the smallest dupe score below this point otherwise

second column is the highest dupe score below this point

third column is xxx if there is no files in this folder,
third column is numeric if there is duplicate files in this folder

 \033[47;48;5;28;1mgreen folders\033[0m are 100% dupes and safe to delete
\033[33myellow folders\033[0m contain some dupes and so does all subfolders
\033[35mpurple folders\033[0m have subfolders which are not dupes
   \033[31mred folders\033[0m contain only unique data
  \033[36mblue folders\033[0m should not appear, let me know if you see one

use shift-pgup/pgdn to scroll, Q to return, ^C to exit
""")

		ch = None
		scr_y = 0
		while True:
			scr_w, scr_h = termsize()
			
			ch = getch()
			if ch in ['\003']:
				return 'x'
			
			if ch in ['u', 'q']:
				return ch


	def foldercomp(self):
		ch = None
		idupe = 0
		scr_y = 0
		while True:
			scr_w, scr_h = termsize()
			panel_w = int(((scr_w + 1) / 2) - 1)
			
			if ch == 'a':
				scr_y = 0
				idupe -= 1
				if idupe < 0:
					idupe = len(self.dupes)-1
			
			if ch == 'd':
				scr_y = 0
				idupe += 1
				if idupe >= len(self.dupes):
					idupe = 0
			
			score, fld1, fld2 = self.dupes[idupe]
			
			if ch == 'e':
				# very safe assumption that urxvt and host has the same font size
				# and that host-terminal is running fullscreen but urxvt won't be
				geom = '{}x{}'.format(scr_w, scr_h - 1).encode('ascii')
				
				if VT100:
					try:
						sp.Popen([
							b'urxvt', b'-title', b'ranger', b'+sb', b'-bl', b'-geometry', geom, b'-e',
							b'ranger', fsenc(fld1.path), fsenc(fld2.path) ])
					except:
						print('could not run urxvt and/or ranger')
						time.sleep(1)
				else:
					sp.Popen(['explorer.exe', fld1.path])
					time.sleep(0.5)  # orz
					sp.Popen(['explorer.exe', fld2.path])
				
				# we could poke urxvt into maximized after startup
				# but that looks bad and why is this even necessary idgi
				if False:
					for n in range(5):
						time.sleep(0.1)
						sp.Popen(['wmctrl', '-r', ':ACTIVE:', '-b', 'add,fullscreen'])
			
			if ch == 'r':
				pass  # redraw
			
			# start with just the header
			scrn = '\033[H\033[0;1;40m{idupe} / {ndupes}  \033[{sc_c}m{sc_v}%\033[0;40m  ←dupe→  ↑screen↓  E/Q  \033[0;36;40m{gt1:.2f}s + {gt2:.2f}s\n\033[0m'.format(
				idupe = idupe + 1,
				ndupes = len(self.dupes),
				sc_c = colorize_score(score),
				sc_v = int(score*100),
				gt1 = self.gen_time[0],
				gt2 = self.gen_time[1]
			)
			
			# adding the two folder paths,
			# start by finding the longest parent-path and folder name,
			# if these fit within scr_w we can align the paths on the last /
			sep = '{}'.format(os.path.sep)
			max_parent = 0
			max_leaf = 0
			paths = [fld1.path, fld2.path]
			for path in paths:
				try:
					a, b = path.rsplit(sep, 1)
				except:
					a = ''
					b = path
				
				max_parent = max(max_parent, len(a))
				max_leaf = max(max_leaf, len(b)+1)
			
			# center_pad is set to the padding amount if we can align on /
			# otherwise the paths are left-aligned and maybe truncated
			center_pad = 0
			if max_parent + max_leaf < scr_w:
				center_pad = int((scr_w - (max_parent + max_leaf)) / 2)
			
			for path in paths:
				spent = center_pad
				scrn += ' ' * center_pad
				
				try:
					a, b = termsafe(path).rsplit(sep, 1)
				except:
					a = ''
					b = termsafe(path)

				b = sep + b
				ln = max_parent - len(a)
				scrn += ' ' * ln
				spent += ln
				
				scrn += '\033[0;36m' + a
				spent += len(a)
				
				b = b[:scr_w-spent]
				scrn += '\033[1;37m' + b + '\033[0m'
				spent += len(b)
				
				scrn += ' ' * (scr_w - spent)
			
			# the left and right panels listing the two folders
			def asdf(fld):
				try:
					statlist = read_folder(fld.path)
				except:
					statlist = [[-3, -3, 'folder 404 (press U to rescan)']]
				
				sizes = [x[0] for x in statlist]
				return statlist, sizes
			
			statlist1, sizes1 = asdf(fld1)
			statlist2, sizes2 = asdf(fld2)
			pan1 = draw_panel(panel_w, statlist1, sizes2)
			pan2 = draw_panel(panel_w, statlist2, sizes1)
			file_rows = []
			
			# this is probably where the view branches will merge
			
			panel_viewport_h = scr_h - 3
		
			if ch == 'w':
				scr_y = max(scr_y - panel_viewport_h, 0)
			
			if ch == 's':
				scr_y += panel_viewport_h
			
			# clamp panels to fit vertically
			tallest_panel = max(len(pan1), len(pan2))
			max_scr_y = max(0, tallest_panel - panel_viewport_h)
			if scr_y > max_scr_y:
				scr_y = max_scr_y
			
			pan1 = pan1[scr_y : scr_y + panel_viewport_h]
			pan2 = pan2[scr_y : scr_y + panel_viewport_h]

			scrollbar_y = int(panel_viewport_h * (scr_y / tallest_panel))
			scrollbar_h = int(math.ceil(panel_viewport_h * (panel_viewport_h / tallest_panel)))
			scrollbar = \
				(['\033[0;1;34m|'] * scrollbar_y) + \
				(['\033[0;1;46;37m|'] * scrollbar_h)
			
			scrollbar.extend(['\033[0;1;34m|'] * (panel_viewport_h - len(scrollbar)))
			
			y=3
			while pan1 or pan2:
				y += 1
				v = []
				for pan in [pan1,pan2]:
					if pan:
						v.append(pan.pop(0))
					else:
						v.append(' ' * panel_w)
				
				file_rows.append(
					#'{}\033[1;34m|\033[0m{}\033[0m'.format(*v))
					'\033[{y}H\033[0m\033[K{f1}\033[{y};{x}H{scrollbar}\033[0m{f2}\033[0m'.format(
						y=y,
						x=panel_w+1,
						f1=termsafe(v[0]),
						f2=termsafe(v[1]),
						scrollbar=scrollbar.pop(0)))
			
			scrn += '\n'.join(file_rows)
			scrn = scrn.replace('\n', '\033[K\n') + '\033[J'
			
			if VT100:
				print(scrn, end='')
			else:
				wprint(scrn)
			
			ch = getch()
			print('\033[G\r\033[K', end='')  # repurpose last line
			
			if ch in ['\003']:
				return 'x'
			
			if ch in ['u', 'q']:
				return ch


def main():
	if len(sys.argv) < 2:
		print('give me folders to scan as arguments,')
		print('for example "." for current folder')
		sys.exit(1)
	
	roots = []
	for root in sys.argv[1:]:
		roots.append(os.path.abspath(os.path.realpath(root)))
	
	cache_path = os.path.join(tempfile.gettempdir(), 'smf.cache')
	print('using', cache_path)

	view = 1
	tui = TUI(os.path.abspath(os.path.realpath(os.getcwd())))
	
	dupes = []
	while True:
		if not dupes:
			if os.path.isfile(cache_path):
				print('loading cache')
				dupes = load_dupe_map(cache_path)
				gen_time = [0., 0.]
			else:
				dupes, gen_time = gen_dupe_map(roots)
				print('saving cache')
				save_dupe_map(cache_path, dupes)
				tui.gen_time = gen_time
		
			tui.set_dupes(dupes)
		
		if not dupes:
			print('you have no dupes ;_;')
			os.remove(cache_path)
			return

		if view == 1:
			rv = tui.foldercomp()
		else:
			rv = tui.tree()
		
		if rv == 'q':
			view += 1
			if view > 2:
				view = 1
		
		if rv == 'x':
			return
		
		if rv == 'u':
			dupes = None
			os.remove(cache_path)


def prof_collect():
	import cProfile
	cProfile.run('gen_dupe_map()', '/dev/shm/prof')


def prof_display():
	import pstats
	from pstats import SortKey
	p = pstats.Stats('/dev/shm/prof')
	p.strip_dirs().sort_stats(SortKey.CUMULATIVE).print_stats()


if __name__ == '__main__':
	#print('[{}]'.format(repr(getch())))
	main()
	#prof_collect()
	#prof_display()


"""
{
printf 'p .%s\nf 1234\n' \
/home/ed/t \
/usr/share/icons/Adwaita/64x64/actions \
/home/ed/t \
/home/ed/t

printf 'd 89 0 1\nd 69 2 3\neof\n'
} | gzip -c > /dev/shm/smf.cache
"""
