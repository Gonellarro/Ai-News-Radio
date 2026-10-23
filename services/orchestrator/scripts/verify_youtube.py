"""Offline verification of real playlist transitions. Never connects to YouTube."""
from pathlib import Path
import json,os,sqlite3,subprocess,time
from datetime import datetime,timezone
from news_orchestrator import config, lifetime
from news_orchestrator.youtube_media import command

base=config.DATA
root=base/'diagnostics'/('youtube-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
root.mkdir()
clips=[]
with lifetime.locked():
 db=sqlite3.connect(f'file:{base / "orchestrator.sqlite3"}?mode=ro',uri=True)
 for index,(job_id,) in enumerate(db.execute("SELECT id FROM jobs WHERE active=1 AND status='ready' ORDER BY published_at DESC")):
  folder=base/'media'/job_id
  manifest=folder/'clip.m3u8'
  if not manifest.is_file():continue
  items=[];duration=None
  for line in manifest.read_text().splitlines():
   if line.startswith('#EXTINF:'):duration=float(line.split(':',1)[1].rstrip(','))
   elif line and not line.startswith('#'):
    name=f'piece-{index:02d}-{len(items):03d}.ts'
    os.link(folder/line,root/name)
    items.append((name,duration))
  clips.append(items)
 db.close()
lines=['#EXTM3U','#EXT-X-VERSION:6','#EXT-X-TARGETDURATION:8','#EXT-X-PLAYLIST-TYPE:VOD','#EXT-X-MEDIA-SEQUENCE:0']
if not clips or not all(clips):
 raise RuntimeError('La parrilla no tiene noticias segmentadas para verificar.')
duration=0;transitions=0
while duration<1500:
 for clip in clips:
  if transitions:lines.append('#EXT-X-DISCONTINUITY')
  transitions+=1
  for name,seconds in clip:
   lines.extend([f'#EXTINF:{seconds:.6f},',name]);duration+=seconds
lines.append('#EXT-X-ENDLIST')
manifest=root/'verification.m3u8';manifest.write_text('\n'.join(lines)+'\n')
output=root/'output.flv';log=root/'ffmpeg.log'
print(json.dumps({'directory':str(root),'input_seconds':duration,'transitions':transitions-1}),flush=True)
started=time.monotonic()
try:
 with log.open('w') as err:
  result=subprocess.run(command(str(manifest),str(output),realtime=False),stdout=subprocess.DEVNULL,stderr=err,timeout=600)
 if result.returncode:raise RuntimeError(log.read_text()[-2000:])
 packets=subprocess.Popen(['ffprobe','-v','error','-show_packets','-show_entries','packet=stream_index,pts_time,dts_time,duration_time','-of','compact=p=0:nk=0',str(output)],stdout=subprocess.PIPE,text=True)
 streams={}
 for line in packets.stdout:
  fields=dict(pair.split('=',1) for pair in line.strip().split('|') if '=' in pair)
  if 'dts_time' not in fields or fields['dts_time']=='N/A':continue
  key=fields['stream_index'];dts=float(fields['dts_time']);pts=float(fields.get('pts_time',fields['dts_time']))
  info=streams.setdefault(key,{'first_dts':dts,'last_dts':None,'last_pts':pts,'packets':0,'backwards':0,'equal':0,'max_gap':0})
  if info['last_dts'] is not None:
   gap=dts-info['last_dts'];info['backwards']+=gap<0;info['equal']+=gap==0;info['max_gap']=max(info['max_gap'],gap)
  info['last_dts']=dts;info['last_pts']=max(info['last_pts'],pts);info['packets']+=1
 if packets.wait():raise RuntimeError('ffprobe failed')
 warnings=log.read_text()
 report={'input_seconds':round(duration,3),'transitions':transitions-1,'streams':streams,'elapsed_seconds':round(time.monotonic()-started,2),'non_monotonic_warnings':sum('non-monoton' in line.lower() for line in warnings.splitlines())}
 report['passed']=(report['non_monotonic_warnings']==0 and all(v['backwards']==0 and v['equal']==0 for v in streams.values()) and abs(streams['0']['last_dts']-streams['1']['last_dts'])<0.2 and abs(streams['1']['last_dts']-duration)<0.3 and streams['1']['max_gap']<0.025)
 (root/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
 if not report['passed']:raise RuntimeError('Clock verification failed; inspect report.json')
finally:
 for p in root.glob('*.ts'):p.unlink()
 output.unlink(missing_ok=True)
