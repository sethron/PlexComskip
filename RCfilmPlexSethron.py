#!/usr/bin/python

import ConfigParser
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

# Config stuff.
config_file_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'RCfilmPlexPostWin.conf')
if not os.path.exists(config_file_path):
  print 'Config file not found: %s' % config_file_path
  print 'Make a copy of RCfilmPlexPost.conf.example named RCfilmPlexPost.conf, modify as necessary, and place in the same directory as this script.'
  sys.exit(1)

config = ConfigParser.SafeConfigParser({
    'comskip-ini-path' : os.path.join(os.path.dirname(os.path.realpath(__file__)), 'comskip.ini'),
    'temp-root' : tempfile.gettempdir(),
    'nice-level' : '0',
    'transcode-after-comskip' : False,
    'stash-original' : False
})
config.read(config_file_path)

COMSKIP_PATH = os.path.expandvars(os.path.expanduser(config.get('Helper Apps', 'comskip-path')))
COMSKIP_INI_PATH = os.path.expandvars(os.path.expanduser(config.get('Helper Apps', 'comskip-ini-path')))
FFMPEG_PATH = os.path.expandvars(os.path.expanduser(config.get('Helper Apps', 'ffmpeg-path')))
HANDBRAKECLI_PATH = os.path.expandvars(os.path.expanduser(config.get('Helper Apps', 'HandBrakeCLI-path')))
#MEDIAINFO_PATH = os.path.expandvars(os.path.expanduser(config.get('Helper Apps', 'mediainfo-path')))
LOG_FILE_PATH = os.path.expandvars(os.path.expanduser(config.get('Logging', 'logfile-path')))
STASH_DIR_PATH = os.path.expandvars(os.path.expanduser(config.get('File Manipulation', 'stash-dir')))
CONSOLE_LOGGING = config.getboolean('Logging', 'console-logging')
TEMP_ROOT = os.path.expandvars(os.path.expanduser(config.get('File Manipulation', 'temp-root')))
COPY_ORIGINAL = config.getboolean('File Manipulation', 'copy-original')
SAVE_ALWAYS = config.getboolean('File Manipulation', 'save-always')
SAVE_FORENSICS = config.getboolean('File Manipulation', 'save-forensics')
NICE_LEVEL = config.get('Helper Apps', 'nice-level')
#MAX_VERT_RES = int(config.get('Transcoding', 'max-vertical-resolution'))
TRANSCODE = config.getboolean('Transcoding', 'transcode-after-comskip')
STASH_ORIGINAL = config.getboolean('File Manipulation', 'stash-original')

# Logging.
session_uuid = str(uuid.uuid4())
fmt = '%%(asctime)-15s [%s] %%(message)s' % session_uuid[:6]
if not os.path.exists(os.path.dirname(LOG_FILE_PATH)):
  os.makedirs(os.path.dirname(LOG_FILE_PATH))
logging.basicConfig(level=logging.INFO, format=fmt, filename=LOG_FILE_PATH)
if CONSOLE_LOGGING:
  console = logging.StreamHandler()
  console.setLevel(logging.INFO)
  formatter = logging.Formatter('%(message)s')
  console.setFormatter(formatter)
  logging.getLogger('').addHandler(console)

# Human-readable bytes.
def sizeof_fmt(num, suffix='B'):

  for unit in ['','K','M','G','T','P','E','Z']:
    if abs(num) < 1024.0:
      return "%3.1f%s%s" % (num, unit, suffix)
    num /= 1024.0
  return "%.1f%s%s" % (num, 'Y', suffix)

if len(sys.argv) < 2:
  print 'Usage: RCfilmPlexPost.py input-file'
  sys.exit(1)

# Clean up after ourselves and exit.
def cleanup_and_exit(temp_dir, keep_temp=False):
  if keep_temp:
    logging.info('Leaving temp files in: %s' % temp_dir)
  else:
    try:
      os.chdir(os.path.expanduser('~'))  # Get out of the temp dir before we nuke it (causes issues on NTFS)
      shutil.rmtree(temp_dir)
    except Exception, e:
      logging.error('Problem whacking temp dir: %s' % temp_dir)
      logging.error(str(e))
      sys.exit(1)

  # Exit cleanly.
  logging.info('Done processing!')
  sys.exit(0)

# If we're in a git repo, let's see if we can report our sha.
logging.info('RCfilmPlexSethron got invoked from %s' % os.path.realpath(__file__))
#try:
#  git_sha = subprocess.check_output('git rev-parse --short HEAD', shell=True)
#  if git_sha:
#    logging.info('Using version: %s' % git_sha.strip())
#except: pass

# Set our own nice level and tee up some args for subprocesses (unix-like OSes only).
NICE_ARGS = []
if sys.platform != 'win32':
  try:
    nice_int = max(min(int(NICE_LEVEL), 20), 0)
    if nice_int > 0:
      os.nice(nice_int)
      NICE_ARGS = ['nice', '-n', str(nice_int)]
  except Exception, e:
    logging.error('Couldn\'t set nice level to %s: %s' % (NICE_LEVEL, e))

# On to the actual work.
try:
  video_path = os.path.abspath(sys.argv[1])
  temp_dir = os.path.join(TEMP_ROOT, session_uuid)
  os.makedirs(temp_dir)
  os.chdir(temp_dir)

  logging.info('Using session ID: %s' % session_uuid)
  logging.info('Using temp dir: %s' % temp_dir)
  logging.info('Using input file: %s' % video_path)


  original_video_dir = os.path.dirname(video_path)
  video_basename = os.path.basename(video_path)
  video_name, video_ext = os.path.splitext(video_basename)

except Exception, e:
  logging.error('Something went wrong setting up temp paths and working files: %s' % e)
  sys.exit(0)

try:
  if COPY_ORIGINAL or SAVE_ALWAYS:
    temp_video_path = os.path.join(temp_dir, video_basename)
    logging.info('Copying file to work on it: %s' % temp_video_path)
    shutil.copy(video_path, temp_dir)
  else:
    temp_video_path = video_path

  # Process with comskip.
  cmd = [COMSKIP_PATH, '--output', temp_dir, '--ini', COMSKIP_INI_PATH, temp_video_path]
  logging.info('[comskip] Command: %s' % cmd)
  subprocess.call(cmd)

except Exception, e:
  logging.error('Something went wrong during comskip analysis: %s' % e)
  cleanup_and_exit(temp_dir, SAVE_ALWAYS or SAVE_FORENSICS)

#process the comskip output and generate segments
edl_file = os.path.join(temp_dir, video_name + '.edl')
logging.info('Using EDL: ' + edl_file)
try:
  segments = []
  prev_segment_end = 0.0
  if os.path.exists(edl_file):
    with open(edl_file, 'rb') as edl:

      # EDL contains segments we need to drop, so chain those together into segments to keep.
      for segment in edl:
        start, end, something = segment.split()
        if float(start) == 0.0:
          logging.info('Start of file is junk, skipping this segment...')
        else:
          keep_segment = [float(prev_segment_end), float(start)]
          logging.info('Keeping segment from %s to %s...' % (keep_segment[0], keep_segment[1]))
          segments.append(keep_segment)
        prev_segment_end = end

  # Write the final keep segment from the end of the last commercial break to the end of the file.
  keep_segment = [float(prev_segment_end), -1]
  logging.info('Keeping segment from %s to the end of the file...' % prev_segment_end)
  segments.append(keep_segment)

  segment_files = []
  segment_list_file_path = os.path.join(temp_dir, 'segments.txt')
  with open(segment_list_file_path, 'wb') as segment_list_file:
    for i, segment in enumerate(segments):
      segment_name = 'segment-%s' % i
      segment_file_name = '%s%s' % (segment_name, video_ext)
      if segment[1] == -1:
        duration_args = []
      else:
        duration_args = ['-t', str(segment[1] - segment[0])]
      cmd = [FFMPEG_PATH, '-i', temp_video_path, '-ss', str(segment[0])]
      cmd.extend(duration_args)
      cmd.extend(['-c', 'copy', segment_file_name])
      logging.info('[ffmpeg] Command: %s' % cmd)
      try:
        subprocess.call(cmd)
      except Exception, e:
        logging.error('Exception running ffmpeg: %s' % e)
        cleanup_and_exit(temp_dir, SAVE_ALWAYS or SAVE_FORENSICS)

      # If the last drop segment ended at the end of the file, we will have written a zero-duration file.
      if os.path.exists(segment_file_name):
        if os.path.getsize(segment_file_name) < 1000:
          logging.info('Last segment ran to the end of the file, not adding bogus segment %s for concatenation.' % (i + 1))
          continue

        segment_files.append(segment_file_name)
        segment_list_file.write('file %s\n' % segment_file_name)

except Exception, e:
  logging.error('Something went wrong during splitting: %s' % e)
  cleanup_and_exit(temp_dir, SAVE_ALWAYS or SAVE_FORENSICS)

#concat files into new mp4
logging.info('Going to concatenate %s files from the segment list.' % len(segment_files))
try:
  cmd = [FFMPEG_PATH, '-y', '-f', 'concat', '-i', segment_list_file_path, '-c', 'copy', os.path.join(temp_dir, video_basename)]
  logging.info('[ffmpeg] Command: %s' % cmd)
  subprocess.call(cmd)

except Exception, e:
  logging.error('Something went wrong during concatenation: %s' % e)
  cleanup_and_exit(temp_dir, SAVE_ALWAYS or SAVE_FORENSICS)

#IF specified, transcode into HEVC
if TRANSCODE:
  logging.info('Going to transcode the file to mp4')
  try:
   ffmpeg_args = [HANDBRAKECLI_PATH, '-i', os.path.join(temp_dir, video_basename), '-o', os.path.join(temp_dir, 'temp.mp4'), '--format', 'av_mp4', '--encoder', 'x264', '--quality', '20' , '--x264-preset', 'veryfast' ]
   transcode_cmd = ffmpeg_args
   logging.info('[HBCLI] Command: %s' % transcode_cmd)
   subprocess.call(transcode_cmd)

  except Exception, e:
    logging.error('Something went wrong during transcoding: %s' % e)
    cleanup_and_exit(temp_dir, SAVE_ALWAYS or SAVE_FORENSICS)

#Sanity check the file and copy back  TODO move this to more logical place
logging.info('Sanity checking our work...')
try:
  input_size = os.path.getsize(os.path.abspath(video_path))
  output_size = os.path.getsize(os.path.abspath(os.path.join(temp_dir, video_basename)))
  if input_size and 1.01 > float(output_size) / float(input_size) > 2.0:
    logging.info('Output file size was too similar (doesn\'t look like we did much); we won\'t replace the original: %s -> %s' % (sizeof_fmt(input_size), sizeof_fmt(output_size)))
    cleanup_and_exit(temp_dir, SAVE_ALWAYS)
  elif input_size and 1.1 > float(output_size) / float(input_size) > 0.1:
    logging.info('Output file size looked sane, we\'ll replace the original: %s -> %s' % (sizeof_fmt(input_size), sizeof_fmt(output_size)))
    #If we have a trash-dir then copy out the original file before copying over it
    if STASH_ORIGINAL:
      logging.info('Copying the original file into the stash directory: %s -> %s' % (video_basename, STASH_DIR_PATH))
      shutil.copyfile(os.path.join(original_video_dir, video_basename), os.path.join(STASH_DIR_PATH, video_basename) )
    #now copy the file back into place
    if TRANSCODE:
      output_file = os.path.join(temp_dir, 'temp.mp4')
      logging.info('Copying the transcoded file into place: %s -> %s' % ((video_name + '.mp4'), original_video_dir))
      shutil.copyfile(output_file, os.path.join(original_video_dir, (video_name + '.mp4') ) )
      logging.info('Deleting the original file: %s in %s' % (video_basename, original_video_dir))
      os.unlink(os.path.join(original_video_dir, video_basename))
    else:
      output_file = os.path.join(temp_dir, video_basename)
      logging.info('Copying the output file into place: %s -> %s' % (video_basename, original_video_dir))
      shutil.copyfile(output_file, os.path.join(original_video_dir, video_basename) )
    cleanup_and_exit(temp_dir, SAVE_ALWAYS)
  else:
    logging.info('Output file size looked wonky (too big or too small); we won\'t replace the original: %s -> %s' % (sizeof_fmt(input_size), sizeof_fmt(output_size)))
    cleanup_and_exit(temp_dir, SAVE_ALWAYS or SAVE_FORENSICS)
except Exception, e:
  logging.error('Something went wrong during sanity check: %s' % e)
  cleanup_and_exit(temp_dir, SAVE_ALWAYS or SAVE_FORENSICS)
