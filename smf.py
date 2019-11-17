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
import bz2
import struct
import pprint
import base64
import hashlib
import tempfile
import platform
import builtins
import threading
import subprocess as sp
from datetime import datetime
from queue import Queue


"""smf.py: file undupe by sizematching files in folders"""
__version__   = "0.3"
__author__    = "ed <smf@ocv.me>"
__credits__   = ["stackoverflow.com"]
__license__   = "MIT"
__copyright__ = 2019


# search for "option:" to see tweakable things below
# (these will become proper options/arguments eventually)


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

	import msvcrt  # pylint: disable=import-error
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
		
		# bufx, bufy, curx, cury, wattr, left, top, right, bottom, maxx, maxy
		left, top, right, bottom = struct.unpack(
			'hhhhHhhhhhh', csbi.raw)[5:-2]
		
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


def termsafe(txt):
	try:
		return txt.encode(TERM_ENCODING, 'backslashreplace').decode(TERM_ENCODING)
	except:
		return txt.encode(TERM_ENCODING, 'replace').decode(TERM_ENCODING)


def print(*args, **kwargs):
	try:
		builtins.print(*list(args), **kwargs)
	except:
		builtins.print(termsafe(' '.join(str(x) for x in args)), **kwargs)


class Folder(object):
	"""
	the absolute path to a folder, and
	the size of each file directly within
	"""
	def __init__(self, path):
		self.path = path
		self.files = []
		self.hashes = {}
	
	def __str__(self):
		return '\033[36m{:6} \033[35m{:12}\033[0m {}'.format(
			len(self.files), sum(self.files), self.path)


class DiskWalker(object):
	def __init__(self, top):
		if ':' in top:
			self.from_rfl(top)
			return
		
		self.cur_top = top
		self.folders = []
		self.errors = []
		
		self.re_usenet = r'\.(r[0-9]{2}|part[0-9]+\.rar)$'
		
		thr = threading.Thread(target=self.logger)
		thr.daemon = True
		thr.start()
		
		print('\n\033[32mentering\033[0m', top)
		self.dev_id = os.lstat(fsenc(top)).st_dev
		self.walk(top)
		self.cur_top = None
		print('\033[32mleaving\033[0m', top)

	def from_rfl(self, top):
		top, rfl = top.split(':', 1)
		print('loading [{}] from rfl [{}]'.format(top, rfl))
		# ./hd/t5/revo.dd.tar.gz //  [-rwxr-xr-x/20656344319/ed:ed] @1247779616
		ptn = re.compile('(.*) // (.*) \[([dlrwx-]{10})/([0-9]+)/([^]]+)\] @([0-9]+)$')
		folders = {}
		with bz2.open(rfl, 'rb') as f:
			for ln in f:
				m = ptn.match(ln.decode('utf-8', 'replace').strip())
				if not m:
					continue
				
				try:
					fn, lnk, modes, sz, owner, ts = m.groups()
					fdir, fn = fn.rsplit('/', 1)
					sz = int(sz)
				except Exception as ex:
					raise Exception('could not parse {}\n{}\n'.format(
						ln, str(ex)))
				
				if sz <= 0:
					continue
				
				try:
					folders[fdir].append(sz)
				except:
					folders[fdir] = [sz]

		self.errors = []
		self.folders = []
		for fpath, fsizes in folders.items():
			folder = Folder(fpath)
			folder.files = fsizes
			sz = sum(fsizes)
			
			if sz > 1*1024*1024 \
			and (len(fsizes) > 2 or sz >= 512*1024*1024):
				self.folders.append(folder)

	def oof(self, *msg):
		msg = ' '.join(str(x) for x in msg)
		self.errors.append(msg)
		print(msg)
	
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
		# option: exclude directory
		#if '/zq1/hd/bismuth' in top: return

		self.cur_top = top
		dev_id = self.dev_id
		folder = Folder(top)
		btop = fsenc(top)
		for bfn in sorted(os.listdir(btop)):
			bpath = os.path.join(btop, bfn)
			if b'\n' in bpath:
				continue
			
			try:
				sr = os.lstat(bpath)
			except KeyboardInterrupt:
				raise
			except:
				self.oof('\033[1;31maccess denied:\033[0m', fsdec(bpath))
				continue
			
			mode = sr.st_mode
			
			if stat.S_ISLNK(mode):
				continue
			
			elif sr.st_dev != dev_id:
				self.oof('\033[35mskipping mountpoint:\033[0m', fsdec(bpath))
			
			elif stat.S_ISDIR(mode):
				try:
					self.walk(fsdec(bpath))
				except KeyboardInterrupt:
					raise
				except:
					self.oof('\033[1;31maccess denied:\033[0m', fsdec(bpath))

			elif not stat.S_ISREG(mode):
				continue
			
			if sr.st_size <= 0:
				continue
			
			folder.files.append(sr.st_size)

		sz = sum(folder.files)
		
		if folder.files \
		and sz > 1*1024*1024 \
		and (len(folder.files) > 2 or sz >= 512*1024*1024):
			self.folders.append(folder)


def gen_dupe_map(roots):
	print("\nscanning disk...")
	
	t0 = time.time()
	folders = []
	errors = []
	
	snap_path = os.path.join(tempfile.gettempdir(), 'smf.snap')
	if os.path.isfile(snap_path):
		with gzip.open(snap_path, 'rb') as f:
			while True:
				ln = f.readline()[:-1].decode('utf-8', ENC_FILTER)
				if ln == 'eof':
					break
				
				if not ln.startswith('p '):
					raise Exception('p expected, got ' + ln)
				
				ln2 = f.readline()[:-1].decode('utf-8')
				if not ln2.startswith('f '):
					raise Exception('f expected, got ' + ln2)
					
				folder = Folder(ln[2:])
				for sz in ln2[2:].split(' '):
					folder.files.append(int(sz))
				
				folders.append(folder)
	else:
		for root in roots:
			dw = DiskWalker(root)
			folders.extend(dw.folders)
			errors.extend(dw.errors)
	
	if errors:
		print('{} errors occurred:'.format(len(errors)))
		for error in errors:
			print(error)
		
		print('these will be repeated after the dupemap generation finishes')
	
	if not os.path.isfile(snap_path):
		print("\ndumping snapshot to", snap_path)
		with gzip.open(snap_path, 'wb') as f:
			for fld in folders:
				txt = 'p {}\nf {}\n'.format(fld.path,
					' '.join(str(x) for x in fld.files))
				
				f.write(txt.encode('utf-8', ENC_FILTER))
			
			f.write(b'eof\n')
	
	print("generating dupemap (hope you're using pypy w)")

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
		
		mnt = folder1.path[:8]  # pylint: disable=unused-variable
		
		for folder2 in folders[nth:]:

			# option: uncomment to only compare between different drives
			# (first 8 letters of each absolute path must be different)
			if folder2.path.startswith(mnt): continue
			
			
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
			
			# sufficiently large hits skip all the checks
			if sum(hits) < 600 * 1024 * 1024:
				
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
	
	if errors:
		print('\nok so about those errors from before,')
		for error in errors:
			print(error)
		
		print('\nare these {} errors ok? press ENTER to continue or CTRL-C'.format(len(errors)))
		input()
	
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
			ret.append([sr.st_size, int(sr.st_mtime), fn])
		else:
			n = -3
			if stat.S_ISLNK(mode):
				n = -2
			elif stat.S_ISDIR(mode):
				n = -1
			
			ret.append([n, n, fn])
	
	return ret


def draw_panel(panel_w, stf, other_sizes, htab1, htab2):
	htab1 = dict(htab1)
	htab2 = dict(htab2)
	lines = []
	files = []
	meta_len = 21
	fn_len = panel_w - (meta_len + 1)
	for sz, ts, fn in stf:
		meta = ' ' * meta_len
		if sz >= 0:
			c = '0'
			if sz in other_sizes:
				other_sizes.remove(sz)
				c = '1;30;47'  # no-hash = white
				bin_eq = True

				# TODO fix structures in rewrite
				fn2 = None
				for hfn, (hsz, _, _) in htab2.items():
					if hsz == sz:
						fn2 = hfn
						break

				if fn in htab1 and fn2:
					hsz, hts, hsha = htab1[fn]
					_, _, hsha2 = htab2[fn2]
					
					if hsz != sz or hts != ts:
						c = '1;30;43'  # dirty hash = yellow
						bin_eq = False
					elif 'x' in [hsha, hsha2]:
						c = '1;30;44'  # queued = blue
						bin_eq = False
					elif hsha == hsha2:
						c = '1;37;44;48;5;28'  # match = green
						bin_eq = True
					else:
						c = '1;37;41'  # incorrect = red
						bin_eq = False
					
					del htab1[fn]
					del htab2[fn2]

				files.append([bin_eq, fn])
			
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
		
		lines.append('{} \033[{}m{}'.format(
			meta, c, fn[:fn_len].ljust(fn_len)))

	return lines, files


class FSDir(object):
	def __init__(self, path):
		self.path = path
		self.dirs = {}
		self.files = []
		self.smin = 0
		self.smax = -9
		self.scur = -2  # extralevel (unvisited)
		self.dupesize = 0

	def build_until(self, dest, extra_levels=1):
		if extra_levels < 0 or (
			not dest.startswith(self.path) \
			and not self.path.startswith(dest)
		):
			raise Exception('\n[{}]  # self\n[{}]  # dest\n[{}]'.format(
				self.path, dest, extra_levels))
		
		self.scur = -1  # visited + zero files
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
				self.files.append([sr.st_size, int(sr.st_mtime), fn])
			elif stat.S_ISLNK(mode):
				self.files.append([-2, -2, fn])
			elif stat.S_ISDIR(mode):
				path += '/'
				subdir = FSDir(path)
				self.dirs[fn] = subdir

				if dest.startswith(path) \
				or (path.startswith(dest) and extra_levels > 0):
					subdir.build_until(dest, extra_levels)
	
	def gen(self, ret, cmap, lv=0):
		scores = ''.join(['\033[{}m{:>3}%\033[0m '.format(x, y) for x, y in [
			colorize_score(self.smin),
			colorize_score("xxx" if self.smax < -7 else self.smax),
			colorize_score("xxx" if self.scur < 0 else self.scur)]])

		if self.smin == 1: cdir = 2 # purely dupes; green
		elif self.smax < -7: cdir = 1  # purely unique; red
		elif self.smin <= 0.01: cdir = 5  # contains unique folders; purple
		elif self.smin > 0: cdir = 3  # purely folders with dupes; yellow
		else: cdir = 6  # wait what did i forget
		
		sz_v = self.dupesize / (1024*1024)
		if sz_v < 30:
			sz_c = '1;30'
		elif sz_v < 200:
			sz_c = '36'
		elif sz_v < 1000:
			sz_c = '1;33'
		else:
			sz_c = '1;37;44'
		
		# not all folders shown are dupes so don't necessarily have a fld,
		# so using self.path since ram is cheap anyways
		ret.append([
			self.path,
			scores,
			'\033[{sz_c}m{sz_v:>5}\033[0m {pad}\033[0;3{cdir}m{path}\033[0m'.format(
				sz_c = sz_c,
				sz_v = int(sz_v),
				pad = '{}\033[1;3{}m|'.format(' ' * (lv * 2 - 1), lv%8) if lv else '',
				cdir = cmap[cdir],
				path = self.path)])
		
		for _, p in sorted(self.dirs.items()):
			p.gen(ret, cmap, lv + 1)
		
		if self.dirs and not ret[:1]:
			ret.append(None)
		
		return ret

	def dump_tree(self, lv=0):
		pad = '{}\033[1;3{}m|'.format(' ' * (lv * 2 - 1), lv%8) if lv else ''
		ret = '{}\033[0;36m{}\033[0m\n'.format(pad, self.path)
		
		for _, p in sorted(self.dirs.items()):
			ret += p.dump(lv + 1)
		
		for p in self.files:
			ret += '{}\033[0m{}\n'.format(pad, p[2])
		
		return ret


def get_dupe_size(fld1, fld2):
	ret = 0
	rhs = fld2.files[:]
	for sz in fld1.files:
		if sz in rhs:
			ret += sz
			rhs.remove(sz)

	return ret


class GetchInterp(object):
	def __init__(self):
		self.hist = ''

	def g(self):
		c = getch()
		if c == '\033':
			self.hist = c
			return None
		
		if not self.hist:
			return c
		
		if c == '[':
			self.hist += c
			return None
		
		if self.hist == '\033[':
			if c == 'A':
				return 'scroll_up'
			if c == 'B':
				return 'scroll_down'
		
		self.hist = None
		return c


class TUI(object):
	def __init__(self, cur_path):
		self.gen_time = [0,0]
		self.cur_path = cur_path
		self.set_dupes(None)
		
		self.getch = GetchInterp().g
		self.inverted_hilight = False

	def set_dupes(self, dupes):
		self.fcmp_idx = 0
		self.dupes = dupes
		self.fs = None

	def tree(self):
		if not self.fs:
			print('\033[36mbuilding directory tree...\033[0m')
			errors = []
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
							# this one is fine,
							# just means we haven't visited it yet
							try:
								self.fs.build_until(path + '/')
								fsnode = fsnode.dirs[pathnode]
							except:
								# ok something actually went wrong
								# (folder was probably deleted)
								errors.append(pathnode)
					
					fsnode.scur = max(fsnode.scur, score)
					fsnode.dupesize = max(fsnode.dupesize,
						get_dupe_size(fld1, fld2))
			
			# set min/max scores
			def foo1(node):
				smin = 1
				smax = -9
				for _, f in node.dirs.items():
					if f.path == '/dev/shm/smf/':
						print('ya')
					min2, max2 = foo1(f)
					smin = min(smin, min2)
					smax = max(smax, max2)
				
				# >0 = scored
				# -1 = no_files
				# -2 = unvisited
				if node.scur >= 0:
					smin = min(smin, node.scur)
					smax = max(smax, node.scur)
				elif node.scur == -2:
					smin = 0

				node.smin = smin
				node.smax = smax
				return smin, smax

			foo1(self.fs)

			# noise filter: remove folders with no dupes at all
			def foo2(node, parent_has_dupes=False):
				drop = []
				was_dupe = False
				for k, v in node.dirs.items():
					if v.smax > 0:
						was_dupe = True
					else:
						# leave one non-dupe between dupes
						# to ease glancing for unique folders
						if was_dupe:
							was_dupe = False
						else:
							drop.append(k)
				
				# and leave the first non-dupe in general too
				i_have_dupes = node.scur > 0 or node.smax > 0
				if parent_has_dupes or i_have_dupes:
					drop = drop[1:]
				
				for k in drop:
					del node.dirs[k]
			
				for _, v in node.dirs.items():
					foo2(v, i_have_dupes)
			
			# option: uncomment to show less non-dupe folders
			foo2(self.fs)
			
			if errors:
				print('\nfailed to access the following directories:\n')
				for error in errors:
					print('--', error)
				
				print('\nis this ok? press ENTER to continue or CTRL-C\n')
				input()
		
		if not self.inverted_hilight:
			cmap = {
				1: 1,
				2: '7;48;5;28;1',
				3: 3,
				4: 4,
				5: 5,
				6: 6
			}
		else:
			cmap = {
				1: '7;48;5;124;1',
				2: '0;1',
				3: '7;48;5;94;1',
				4: '7;48;5;26;1',
				5: '7;48;5;92;1',
				6: '7;48;5;68;1'
			}

		tree = []
		self.fs.gen(tree, cmap)
		
		scr_y = 0
		dir_ptr = 0
		for n, (path, _, _) in enumerate(tree):
			if path == self.cur_path + '/':
				scr_w, scr_h = termsize()
				scr_y = int(max(0, n - scr_h / 2.5))
				dir_ptr = n
				break

		ch = None
		header = '\033[0;1;40m  min% max% dir%   size  //  ↑dupe↓  ←screen→  Q  \033[0m'
		
		while True:
			scr_w, scr_h = termsize()
			
			# duplicating the scrolling stuff for now,
			# generalize once additional views materialize
			scrn = '\033[H' + header + '\n'
			panel_viewport_h = scr_h - 1
			
			if ch in ['a', 'd']:
				if ch == 'a':
					scr_y = max(scr_y - panel_viewport_h, 0)
				elif ch == 'd':
					scr_y += panel_viewport_h
				
				max_scr_y = max(0, len(tree) - panel_viewport_h)
				if scr_y > max_scr_y:
					scr_y = max_scr_y
				
				if dir_ptr < scr_y:
					dir_ptr = scr_y
				elif dir_ptr >= scr_y + panel_viewport_h:
					dir_ptr = scr_y + panel_viewport_h - 1
			
			elif ch in ['w', 's', 'scroll_up', 'scroll_down']:
				if ch == 'w':
					dir_ptr -= 1
				elif ch == 's':
					dir_ptr += 1
				elif ch == 'scroll_up':
					dir_ptr -= 1
				elif ch == 'scroll_down':
					dir_ptr += 1

				if dir_ptr < 0:
					dir_ptr = len(tree) - 1
				elif dir_ptr >= len(tree):
					dir_ptr = 0
				
				if scr_y > dir_ptr:
					scr_y = dir_ptr
				elif dir_ptr >= scr_y + panel_viewport_h:
					scr_y = (dir_ptr - panel_viewport_h) + 1
			
			active_row = tree[dir_ptr]

			scrollbar_y = int(panel_viewport_h * (scr_y / len(tree)))
			scrollbar_h = int(math.ceil(panel_viewport_h * (panel_viewport_h / len(tree))))
			scrollbar = \
				(['\033[0;1;34m|'] * scrollbar_y) + \
				(['\033[0;1;46;37m|'] * scrollbar_h)
			
			scrollbar.extend(['\033[0;1;34m|'] * (panel_viewport_h - len(scrollbar)))
			
			ansi_y = 1
			rows = []
			for row in tree[scr_y : scr_y + panel_viewport_h]:
				path, scores, line = row
				ansi_y += 1
				
				line_color = '\033[0m'
				gutter = scrollbar.pop(0)
				if row == active_row:
					gutter = '\033[48;5;255m■\033[0m'
					line_color = '\033[1;37;40m'
				
				rows.append(
					'\033[{y}H{gutter}\033[0m \033[K{scores} {lc}{line}\033[0m'.format(
						y=ansi_y,
						gutter=gutter,
						scores=scores,
						lc=line_color,
						line=termsafe(line)[:(scr_w - 5)]))
						# TODO affected by ansi stuff ^
			
			scrn += '\n'.join(rows)
			scrn = scrn.replace('\n', '\033[K\n') + '\033[J'
			
			if VT100:
				print(scrn, end='')
			else:
				wprint(scrn)
			
			ch = self.getch()
			print('\033[G\r\033[K', end='')  # repurpose last line
			
			if ch == '\003':
				return 'x', None
			
			if ch == '?':
				print("""
first column is xxx if there exists purely-unique folders below this point,
first column is numeric with the smallest dupe score below this point otherwise

second column is the highest dupe score below this point

third column is xxx if there is no files in this folder,
third column is numeric if there is duplicate files in this folder

fourth column is disk space consumed by the dupes in megabytes

 \033[1;37;44;48;5;28mgreen folders\033[0m are 100% dupes and safe to delete
\033[33myellow folders\033[0m contain some dupes and so does all subfolders
\033[35mpurple folders\033[0m have subfolders which are not dupes
   \033[31mred folders\033[0m contain only unique data
  \033[36mblue folders\033[0m should not appear, let me know if you see one

use W/S to pgup/pgdn,  A/D to scroll,  Q to return,  ^C to exit

press ENTER to quit this help view
""")
				input()

			if ch == 'q':
				# find nearest folder in the dupeset
				#import pudb; pu.db
				for step in range(20):
					for direction in [1, -1][:step + 1]:
						step *= direction
						n = dir_ptr + step
						if n < 0 or n >= len(tree):
							continue
						
						needle = tree[n][0][:-1]
						for _, fld1, fld2 in self.dupes:
							for fld in [fld1, fld2]:
								if needle == fld.path:
									self.cur_path = fld.path
									return ch, None
				
				# can't be helped
				self.cur_path = self.dupes[0][1].path
				return ch, None
			
			if ch in ['r', 'u', 'v']:
				return ch, None

	def foldercomp(self):
		if self.cur_path != self.dupes[self.fcmp_idx][1].path:
			ok = False
			self.fcmp_idx = 0
			for side in [1, 2]:
				for n, dupe_obj in enumerate(self.dupes):
					if dupe_obj[side].path == self.cur_path:
						self.fcmp_idx = n
						ok = True
						break
				
				if ok:
					break
		
		ch = None
		scr_y = 0
		while True:
			scr_w, scr_h = termsize()
			panel_w = int(((scr_w + 1) / 2) - 1)
			
			if ch == 'a':
				scr_y = 0
				self.fcmp_idx -= 1
				if self.fcmp_idx < 0:
					self.fcmp_idx = len(self.dupes)-1
			
			if ch == 'd':
				scr_y = 0
				self.fcmp_idx += 1
				if self.fcmp_idx >= len(self.dupes):
					self.fcmp_idx = 0
			
			score, fld1, fld2 = self.dupes[self.fcmp_idx]
			self.cur_path = fld1.path
			
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
						time.sleep(0.5)
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
			csc = colorize_score(score)
			
			sz_v = int(get_dupe_size(fld1, fld2) / (1024.*1024))
			if sz_v < 30:
				sz_c = '1;30'
			elif sz_v < 200:
				sz_c = '33'
			else:
				sz_c = '1;37;44'
			
			scrn = '\033[H\033[0;1;40m{idupe} / {ndupes}  \033[{sc_c}m{sc_v}%\033[0;40m  \033[{sz_c}m{sz_v}\033[0;40mMB  ←dupe→  ↑screen↓  E/Q  \033[0;36;40m{gt1:.2f}s + {gt2:.2f}s\n\033[0m'.format(
				idupe = self.fcmp_idx + 1,
				ndupes = len(self.dupes),
				sc_c = csc[0],
				sc_v = csc[1],
				sz_c = sz_c,
				sz_v = sz_v,
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
					stf = read_folder(fld.path)
				except:
					stf = [[-3, -3, 'folder 404 (press U to rescan)']]
				
				sizes = [x[0] for x in stf]
				return stf, sizes
			
			stf1, sizes1 = asdf(fld1)
			stf2, sizes2 = asdf(fld2)
			pan1, dupefiles1 = draw_panel(panel_w, stf1, sizes2, fld1.hashes, fld2.hashes)
			pan2, dupefiles2 = draw_panel(panel_w, stf2, sizes1, fld2.hashes, fld1.hashes)
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
			
			ch = self.getch()
			print('\033[G\r\033[K', end='')  # repurpose last line
			
			if ch == '\003':
				return 'x', None
			
			if ch in ['r', 'u', 'v', 'q']:
				return ch, None

			if ch == 'k':
				print('\033[2A\033[J\033[1;37;41m\033[Jchoose folder to remove dupes from:\n\033[0m\033[J\033[1;37;44m J \033[0m {}\n\033[1;37;44m L \033[0m {}'.format(
					fld1.path, fld2.path), end='')
				
				ch = self.getch()
				if ch == 'j':
					n = 1
				elif ch == 'l':
					n = -1
				else:
					print('\n\n\033[1;37;44m abort \033[0m')
					time.sleep(0.5)
					continue
				
				nuke_path, keep_path = [fld1.path, fld2.path][::n]
				nuke_files, keep_files = [dupefiles1, dupefiles2][::n]
				nuke_side, keep_side = ['LEFT', 'RIGHT'][::n]
				nuke_fld, keep_fld = [fld1, fld2][::n]
				
				print('\033[3A\n\033[1;37;41m\033[JDELETE {}:\033[0;1m {} \033[0m\n\033[J\033[1;37;44m K \033[0m Delete files\n\033[1;37;44m L \033[0m replace with symlinks to files in {} '.format(
					nuke_side, nuke_path, keep_side), end='')
				
				ch = self.getch()
				print('\n')
				
				if ch == 'k':
					return 'rm', [nuke_path, nuke_files]
				elif ch == 'l':
					# main needs *_files ordered, another todo for the rewrite
					# fld.hashes[fname] = [sz, ts, sha1]
					lhs = []
					rhs = []
					for got_hash, fn in nuke_files:
						try:
							_, _, expect = nuke_fld.hashes[fn]
						except:
							continue
						
						for fn2, (sz, ts, sha1) in keep_fld.hashes.items():
							if sha1 == expect:
								lhs.append([True, fn])
								rhs.append([True, fn2])
								break
					
					#return 'ln', [keep_path, keep_files, nuke_path, nuke_files]
					return 'ln', [keep_path, rhs, nuke_path, lhs]
				
				print('\n\n\033[1;37;44m abort \033[0m')
				time.sleep(0.5)
				continue
			
			if ch == 'm':
				print('\033[2A\033[J\033[1;37;41m\033[Jchoose folder to write last-modified to:\n\033[0m\033[J\033[1;37;44m J \033[0m {}\n\033[1;37;44m L \033[0m {}'.format(
					fld1.path, fld2.path), end='')
				
				ch = self.getch()
				if ch == 'j':
					n = 1
				elif ch == 'l':
					n = -1
				else:
					print('\n\n\033[1;37;44m abort \033[0m')
					time.sleep(0.5)
					continue
				
				dstdir, srcdir = [fld1.path, fld2.path][::n]
				dstfiles, srcfiles = [dupefiles1, dupefiles2][::n]
				
				for (srceq, srcfn), (dsteq, dstfn) in zip(srcfiles, dstfiles):
					if not srceq or not dsteq:
						continue
					
					srcpath = os.path.join(srcdir, srcfn)
					dstpath = os.path.join(dstdir, dstfn)
					
					print(dstpath)
					ts = int(os.stat(srcpath).st_mtime)
					os.utime(dstpath, (ts,ts))
						
			if ch == 'n':
				print('\033[2A\033[J\033[1;37;41m\033[Jchoose folder to WRITE FILENAMES to:\n\033[0m\033[J\033[1;37;44m J \033[0m {}\n\033[1;37;44m L \033[0m {}'.format(
					fld1.path, fld2.path), end='')
				
				ch = self.getch()
				if ch == 'j':
					n = 1
				elif ch == 'l':
					n = -1
				else:
					print('\n\n\033[1;37;44m abort \033[0m')
					time.sleep(0.5)
					continue
				
				dstdir, srcdir = [fld1.path, fld2.path][::n]
				dstfiles, srcfiles = [dupefiles1, dupefiles2][::n]
				
				print('\n')
				actions = []
				for (srceq, srcfn), (dsteq, dstfn) in zip(srcfiles, dstfiles):
					if not srceq or not dsteq:
						continue
					
					srcpath = os.path.join(dstdir, dstfn)
					dstpath = os.path.join(dstdir, srcfn)
					actions.append([srcpath, dstpath])
					
					print('old {}\nnew {}\n'.format(*actions[-1]))
				
				print('press ENTER to confirm')
				input()
				
				for p1, p2 in actions:
					print('mv', p1)
					if os.path.exists(p2):
						raise Exception('destination exists: {}'.format(p2))
					
					os.rename(p1, p2)
			
			if ch == 'h':
				# dump the folders and let core handle the rest
				ret = []
				for fld, stf in [
					[fld1, stf1],
					[fld2, stf2]
				]:
					fret = []
					for sz, ts, fn in stf:
						fret.append([sz, ts, fn])
					
					ret.append([fld, fret])
				
				return ch, ret


def hashfile(fpath, fsize, prefix):
	t0 = time.time()
	fpos = 0
	next_print = 0
	print_interval = 1024*1024*16
	last_print_pos = 0
	last_print_ts = t0
	
	hasher = hashlib.sha1()
	with open(fsenc(fpath), 'rb', 512*1024) as f:
		while True:
			if fpos >= next_print:
				now = time.time()
				time_delta = now - last_print_ts
				bytes_delta = fpos - last_print_pos
				if bytes_delta <= 0 or time_delta <= 0:
					perc = 0
					speed = 0
				else:
					perc = (100. * fpos) / fsize
					speed = ((
						(fpos - last_print_pos) /
						(now - last_print_ts)) /
						(1024. * 1024))
				
				next_print += print_interval
				print('\033[A{}{:6.2f}% @ {:8.2f} MiB/s  {}'.format(
					prefix, perc, speed, fpath))
			
			data = f.read(512*1024)
			if not data:
				break
			
			hasher.update(data)
			fpos += len(data)
	
	return base64.b64encode(hasher.digest()
		).decode('ascii').rstrip('='), time.time() - t0


def remove_deleted_folders(dupes):
	# quickrefresh; drops deleted folders from cache
	# (single deleted files is not worth)
	tested = {}
	ok = {}
	ng = {}
	newdupes = []
	for dupe in dupes:
		_, fld1, fld2 = dupe
		for fld in [fld1, fld2]:
			path = fld.path
			if path in tested:
				continue
			
			tested[path] = 1
			
			if os.path.exists(path):
				ok[path] = 1
			else:
				print('forgetting', path)
				ng[path] = 1
		
		if fld1.path in ok \
		and fld2.path in ok:
			newdupes.append(dupe)
	
	if ng:
		print("""
removed {} deleted folders from the cache
(this removes {} dupes from the cache btw)
hit ENTER to save and continue, or press CTRL-C
""".format(len(ng.items()), len(dupes) - len(newdupes)))
		input()

	return ok, ng, newdupes


class Hashd(object):
	def __init__(self, sha1_path, dupes):
		self.sha1_path = sha1_path
		self.dupes = dupes
		
		self.mtx = threading.Lock()
		self.done = Queue()
		self.workers = {}
		
		self.hashtab = {}
		if os.path.exists(sha1_path):
			with open(sha1_path, 'rb') as f:
				for ln in f:
					sha1, sz, ts, fn = ln.decode('utf-8').split(' ', 3)
					self.hashtab[fn.rstrip()] = [int(sz), int(ts), sha1]
		
		by_folder = {}
		for fpath, (sz, ts, sha1) in self.hashtab.items():
			fdir, fname = fpath.rsplit('/', 1)
			entry = [fname, sz, ts, sha1]
			try:
				by_folder[fdir].append(entry)
			except:
				by_folder[fdir] = [entry]
		
		seen = {}
		for _, fld1, fld2 in dupes:
			for fld in [fld1, fld2]:
				if fld in seen:
					continue
				
				seen[fld] = 1
				try:
					fname, sz, ts, sha1 = by_folder[fld.path]
					fld.hashes[fname] = [sz, ts, sha1]
				except:
					pass
	
	def terminate(self):
		for _, worker in self.workers.items():
			worker.put(None)
		
		done = False
		while not done:
			done = True
			time.sleep(0.1)
			for _, worker in self.workers.items():
				if not worker.empty():
					done = False
	
	def add(self, fld, stf):
		sz, ts, fn = stf[0]
		bpath = fsenc(os.path.join(fld.path, fn))
		dev_id = os.lstat(bpath).st_dev
		if dev_id not in self.workers:
			q = Queue()
			self.workers[dev_id] = q
			
			thr = threading.Thread(target=self.worker, args=(q,))
			thr.daemon = True
			thr.start()
		
		self.workers[dev_id].put([fld, stf])
	
	def worker(self, q):
		while True:
			task = q.get()
			if not task:
				return
			
			fld, stf = task
			
			new_hashes = []
			for sz, ts, fname in stf:
				fpath = os.path.join(fld.path, fname)
				sha = None
				with self.mtx:
					if fpath in self.hashtab:
						csz, cts, csha = self.hashtab[fpath]
						if sz == csz and ts == cts:
							sha = csha
				
				if not sha:
					sha = self.hashfile(fpath)
					new_hashes.append([sha, sz, ts, fpath])
				
				fld.hashes[fname] = [sz, ts, sha]
			
			if new_hashes:
				with self.mtx:
					with open(self.sha1_path, 'ba+') as f:
						for item in new_hashes:
							ln = ' '.join(str(x) for x in item) + '\n'
							f.write(ln.encode('utf-8', ENC_FILTER))
					
					for fpath, sz, ts, sha1 in new_hashes:
						self.hashtab[fpath] = [sz, ts, sha1]
	
	def hashfile(self, fpath):
		hasher = hashlib.sha1()
		with open(fsenc(fpath), 'rb', 512*1024) as f:
			while True:
				data = f.read(512*1024)
				if not data:
					break
				
				hasher.update(data)
		
		b64 = base64.b64encode(hasher.digest())
		return b64.decode('ascii').rstrip('=')


def main():
	if len(sys.argv) < 2:
		print('give me folders to scan as arguments,')
		print('for example "." for current folder')
		sys.exit(1)
	
	cache_path = os.path.join(tempfile.gettempdir(), 'smf.cache')
	sha1_path = os.path.join(tempfile.gettempdir(), 'smf.sha1')
	print('using', cache_path)
	print('using', sha1_path)

	roots = []
	for root in sys.argv[1:]:
		if root == '-u':
			for f in [cache_path, sha1_path]:
				try: os.remove(f)
				except: pass
		else:
			roots.append(os.path.abspath(os.path.realpath(root)))
	
	view = 1
	tui = TUI(os.path.abspath(os.path.realpath(os.getcwd())))
	
	dupes = []
	hashd = None
	while True:
		if not dupes:
			gen_time = [0., 0.]
			if os.path.isfile(cache_path):
				print('loading cache')
				xdupes = load_dupe_map(cache_path)
				ok, ng, dupes = remove_deleted_folders(xdupes)
				if len(dupes) != len(xdupes):
					save_dupe_map(cache_path, dupes)
			else:
				dupes, gen_time = gen_dupe_map(roots)
				print('saving cache')
				save_dupe_map(cache_path, dupes)
				tui.gen_time = gen_time
		
			if hashd:
				hashd.terminate()
			
			print('mapping hashtab')
			hashd = Hashd(sha1_path, dupes)
			
			tui.set_dupes(dupes)
		
		if not dupes:
			print('you have no dupes ;_;')
			os.remove(cache_path)
			return

		if view == 1:
			rv, extra = tui.foldercomp()
		else:
			rv, extra = tui.tree()
		
		need_quickrefresh = False
		
		if rv == 'q':
			view += 1
			if view > 2:
				view = 1
		
		if rv == 'x':
			return
		
		if rv == 'r':
			need_quickrefresh = True
		
		if rv == 'u':
			dupes = None
			os.remove(cache_path)
		
		if rv == 'v':
			tui.inverted_hilight = not tui.inverted_hilight
		
		if rv == 'h':
			hashq1 = []
			hashq2 = []
			(fld1, stf1), (fld2, stf2) = extra
			for sz, ts, fn in stf1:
				hit = next((x for x in stf2 if x[0] == sz and sz > 0), None)
				if hit:
					sz2, ts2, fn2 = hit
					hashq1.append([sz, ts, fn])
					hashq2.append(hit)
					stf2.remove(hit)
					fld1.hashes[fn] = [sz, ts, 'x']
					fld2.hashes[fn2] = [sz2, ts2, 'x']
			
			hashd.add(fld1, hashq1)
			hashd.add(fld2, hashq2)
		
		if rv == 'rm':
			nuke_path, nuke_files = extra
			actions = []
			for bin_eq, fn in nuke_files:
				if not bin_eq:
					continue
				
				actions.append(os.path.join(nuke_path, fn))
				print('\033[1;37;41mDEL\033[0m {}'.format(actions[-1]))
			
			print('press ENTER to confirm')
			input()
			
			for path in actions:
				print('rm', path)
				os.remove(path)
			
			try:
				os.rmdir(nuke_path)
				print('\033[32mfolder deleted too')
			except:
				print('\033[31mcould NOT delete folder')
			
			print('\033[0mdone; press ENTER to return')
			#need_quickrefresh = True
			#input()

		if rv == 'ln':
			keep_path, keep_files, \
			nuke_path, nuke_files = extra
			
			actions = []
			for xa, xb in zip(keep_files, nuke_files):
				keep_bineq, keep_fn = xa
				nuke_bineq, nuke_fn = xb
				
				if not keep_bineq or not nuke_bineq:
					continue
				
				keep_abs = os.path.join(keep_path, keep_fn)
				nuke_abs = os.path.join(nuke_path, nuke_fn)
				actions.append([keep_abs, nuke_abs])
				print('ln \033[1;37;44m{}\033[0;1;33m -> \033[1;37;41m{}\033[0m'.format(*actions[-1]))
			
			print('press ENTER to confirm')
			input()
			
			for keep, nuke in actions:
				print('rm', nuke)
				os.remove(nuke)
				os.symlink(keep, nuke)
			
			print('done; press ENTER to return')
			#need_quickrefresh = True
			#input()
		
		if need_quickrefresh:
			ok, ng, dupes = remove_deleted_folders(dupes)
			save_dupe_map(cache_path, dupes)
			tui.set_dupes(dupes)


def prof_collect():
	import cProfile
	cProfile.run('gen_dupe_map()', '/dev/shm/prof')


def prof_display():
	import pstats
	from pstats import SortKey
	p = pstats.Stats('/dev/shm/prof')
	p.strip_dirs().sort_stats(SortKey.CUMULATIVE).print_stats()


def loop_getch():
	while True:
		ch = repr(getch())
		print(ch)
		if ch in ['q', '\003']:
			return


if __name__ == '__main__':
	#print('[{}]'.format(repr(getch())))
	#loop_getch()
	main()
	#prof_collect()
	#prof_display()


"""
TODO
persist y when flipping back to tree
re_usenet
match by hash first then filesize
show hash mismatch count in statusbar
"""
