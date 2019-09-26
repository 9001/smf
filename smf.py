#!/usr/bin/env python3
# coding: utf-8
from __future__ import print_function

import os
import sys
import stat
import time
import gzip
import threading
import subprocess as sp
from datetime import datetime


if sys.platform.startswith('linux') \
or sys.platform == 'darwin':
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

	import fcntl, termios, struct, os
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


elif sys.platform in ['win32','cygwin']:
	raise Exception('untested, remove me if this actually works')
	
	import vcrt
	def getch():
		while msvcrt.kbhit():
			msvcrt.getch()
		
		ch = msvcrt.getch()
		if sys.version_info[0] > 2:
			return ch
		else:
			return ch.decode(encoding='mbcs')

	from ctypes import windll, create_string_buffer, struct
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
		p = sp.Popen(['tput','cols'], stdin=sp.PIPE, stdout=sp.PIPE)
		cols = int(p.communicate(input=None)[0])
		
		p = sp.Popen(['tput','lines'], stdin=sp.PIPE, stdout=sp.PIPE)
		lines = int(p.communicate(input=None)[0])
		
		return [cols, lines]
	
	def termsize():
		return termsize_native() or termsize_ncurses()

else:
	raise Exception('unsupported platform: {}'.format(sys.platform))


########################################################################
########################################################################


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
		
		self.walk(top)
		self.cur_top = None
	
	def logger(self):
		last_top = None
		while True:
			time.sleep(0.05)
			if not self.cur_top:
				break
			
			if last_top == self.cur_top:
				continue
			
			last_top = self.cur_top
			print('reading', self.cur_top)
	
	def walk(self, top):
		self.cur_top = top
		folder = Folder(top)
		for fn in sorted(os.listdir(top)):
			path = os.path.join(top, fn)
			try: sr = os.lstat(path)
			except: continue
			mode = sr.st_mode
			
			if stat.S_ISLNK(mode):
				continue
			
			elif stat.S_ISDIR(mode):
				try:
					self.walk(path)
				except KeyboardInterrupt:
					raise
				except:
					pass

			elif stat.S_ISREG(mode) and sr.st_size > 0:
				folder.files.append(sr.st_size)

		if folder.files \
		and sum(folder.files) > 1*1024*1024 \
		and len(folder.files) > 2:
			self.folders.append(folder)


def gen_dupe_map():
	dw = DiskWalker('.')
	folders = dw.folders
	print("\ngenerating dupemap (hope you're using pypy w)")

	# compare each unique permutation of [Folder,Folder]
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

	return dupes


def save_dupe_map(cache_path, dupes):
	with gzip.open(cache_path, 'wb') as f:
		seen_folders = {}
		n = 0
		
		# serialize folders that contain dupes
		for _, fld1, fld2 in dupes:
			for fld in [fld1, fld2]:
				if fld not in seen_folders:
					txt = u'p {}\nf {}\n'.format(fld.path,
						' '.join(str(x) for x in fld.files))
					
					f.write(txt.encode('utf-8'))
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
			ln = f.readline().decode('utf-8').rstrip()
			if ln.startswith(u'p '):
				ln2 = f.readline().decode('utf-8').rstrip()
				if not ln2.startswith(u'f '):
					raise Exception('non-f after p')
				
				folder = Folder(ln[2:])
				for sz in ln2[2:].split(' '):
					folder.files.append(int(sz))
				
				folders.append(folder)
				continue
			
			if ln.startswith(u'd '):
				score, i1, i2 = [int(x) for x in ln[2:].split(' ')]
				dupes.append([score/1000., folders[i1], folders[i2]])
				continue
			
			if ln == u'eof':
				break
			
			raise Exception('unexpected line: {}'.format(ln))

	return dupes


def dump_summary(dupes):
	# keep track of the 1st folder in the pair,
	# print it as a header for all the folders it matched against
	last_lhs = None
	for score, lhs, rhs in dupes:
		ln = lhs.path
		rn = rhs.path
		if last_lhs != ln:
			last_lhs = ln
			print(u'\n\033[1;37m{:5}{}\033[0m'.format('', ln))
		
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
		else:
			c = '1;37;44;48;5;28'
		
		print(u'\033[{}m{:3d}%\033[0m {}'.format(
			c, int(score*100), rn))


def read_folder(top):
	# TODO have walker use this maybe
	ret = []
	for fn in sorted(os.listdir(top)):
		path = os.path.join(top, fn)
		sr = os.lstat(path)
		mode = sr.st_mode
		
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
			
			ts = datetime.utcfromtimestamp(ts).strftime('%Y-%m%d')
			meta = u'{} {:11}'.format(ts, sz)
		
		elif sz == -2:
			# symlink
			c = '0;33'
		
		elif sz == -1:
			# dir
			c = '0;36'
		
		else:
			# unhandled
			c = '1;31'
		
		ret.append(u'{} \033[{}m{}'.format(
			meta, c, fn[:fn_len].ljust(fn_len)))

	return ret


def gui(dupes):
	ch = None
	idupe = 0
	while True:
		scr_w, scr_h = termsize()
		panel_w = int(((scr_w + 1) / 2) - 1)
		
		if ch == 'w':
			idupe -= 1
			if idupe < 0:
				idupe = len(dupes)-1
		
		if ch == 's':
			idupe += 1
			if idupe >= len(dupes):
				idupe = 0
		
		score, fld1, fld2 = dupes[idupe]
		
		if ch == 'e':
			# very safe assumption that urxvt and host has the same font size
			# and that host-terminal is running fullscreen but urxvt won't be
			geom = '{}x{}'.format(scr_w, scr_h - 1)
			
			sp.Popen([
				'urxvt', '-title', 'ranger', '+sb', '-bl', '-geometry', geom, '-e',
				'ranger', fld1.path, fld2.path ])
			
			# we could poke urxvt into maximized after startup
			# but that looks bad and why is this even necessary idgi
			if False:
				for n in range(5):
					time.sleep(0.1)
					sp.Popen(['wmctrl', '-r', ':ACTIVE:', '-b', 'add,fullscreen'])
		
		if ch == 'r':
			pass  # redraw
		
		if score < 0.2:
			score_color = '1;30'
		elif score < 0.35:
			score_color = '0;31'
		elif score < 0.5:
			score_color = '0;36'
		elif score < 0.7:
			score_color = '0;33'
		elif score < 0.9:
			score_color = '1;32'
		else:
			score_color = '1;37;44;48;5;28'
		
		# start with just the header
		scrn = u'\033[H\033[0;1;40m{idupe} / {ndupes}  \033[{sc_c}m{sc_v}%\033[0;1;40m\n\033[0m'.format(
			idupe = idupe,
			ndupes = len(dupes),
			sc_c = score_color,
			sc_v = int(score*100)
		)
		
		# adding the two folder paths,
		# start by finding the longest parent-path and folder name,
		# if these fit within scr_w we can align the paths on the last /
		max_parent = 0
		max_leaf = 0
		paths = [fld1.path, fld2.path]
		parts = []
		for path in paths:
			a, b = path.rsplit('/', 1)
			max_parent = max(max_parent, len(a))
			max_leaf = max(max_leaf, len(b)+1)
		
		# center_pad is set to the padding amount if we can align on /
		# otherwise the paths are left-aligned and maybe truncated
		center_pad = 0
		if max_parent + max_leaf < scr_w:
			center_pad = int((scr_w - (max_parent + max_leaf)) / 2)
		
		for path in paths:
			spent = center_pad
			scrn += u' ' * center_pad
			
			a, b = path.rsplit('/', 1)
			b = '/' + b
			ln = max_parent - len(a)
			scrn += u' ' * ln
			spent += ln
			
			scrn += u'\033[0;36m' + a
			spent += len(a)
			
			b = b[:scr_w-spent]
			scrn += u'\033[1;37m' + b + '\033[0m'
			spent += len(b)
			
			scrn += u' ' * (scr_w - spent)
		
		# the left and right panels listing the two folders
		def asdf(fld):
			try:
				statlist = read_folder(fld.path)
			except:
				statlist = [[-3, -3, 'could not read folder']]
			
			sizes = [x[0] for x in statlist]
			return statlist, sizes
		
		statlist1, sizes1 = asdf(fld1)
		statlist2, sizes2 = asdf(fld2)
		pan1 = draw_panel(panel_w, statlist1, sizes2)[:scr_h-3]
		pan2 = draw_panel(panel_w, statlist2, sizes1)[:scr_h-3]
		file_rows = []
		
		y=3
		while pan1 or pan2:
			y += 1
			v = []
			for pan in [pan1,pan2]:
				if pan:
					v.append(pan.pop(0))
				else:
					v.append(u' ' * panel_w)
			
			file_rows.append(
				#u'{}\033[1;34m|\033[0m{}\033[0m'.format(*v))
				u'\033[{y}H\033[0m\033[K{f1}\033[{y};{x}H\033[0;1;34m|\033[0m{f2}\033[0m'.format(
					y=y, x=panel_w+1, f1=v[0], f2=v[1]))
		
		scrn += '\n'.join(file_rows)
		print(scrn.replace('\n', '\033[K\n') + '\033[J', end='')
		ch = getch()
		# TODO must handle ^C and \033 on windows


def main():
	cache_path = '/dev/shm/smf.cache'
	if os.path.isfile(cache_path):
		print('loading cache')
		dupes = load_dupe_map(cache_path)
	else:
		dupes = gen_dupe_map()
		print('saving cache')
		save_dupe_map(cache_path, dupes)
	
	if not dupes:
		print('no dupes ;_;')
		return
	
	#dump_summary()
	gui(dupes)


def prof_collect():
	import cProfile
	cProfile.run('gen_dupe_map()', '/dev/shm/prof')


def prof_display():
	import pstats
	from pstats import SortKey
	p = pstats.Stats('/dev/shm/prof')
	p.strip_dirs().sort_stats(SortKey.CUMULATIVE).print_stats()


if __name__ == '__main__':
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
