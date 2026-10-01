import json, os, subprocess, time, hashlib
from pathlib import Path
root=Path('/tmp/madis-load-5d9681a')
root.mkdir(exist_ok=True)
harness=Path('/tmp/madis-verify-5d9681a/source/bench/compare_opensips.py')
base=Path('/tmp/madis-opensips.6Xq9rD')
binaries={'madis':Path('/tmp/madis-verify-5d9681a/madis'),'opensips':base/'opensips/usr/sbin/opensips'}
env={'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','HOME':'/root','LD_LIBRARY_PATH':str(base/'sipp/usr/lib/x86_64-linux-gnu')}
plan=[('smoke',250,5,1), ('sustained',250,30,1), ('sustained',500,30,1), ('soak',250,180,1)]
summary=[]
for stage,rate,seconds,rep in plan:
 order=['madis']
 for kind in order:
  name=f'{stage}-{kind}-{rate}-{seconds}-{rep}'
  output=root/name
  cmd=['python3',str(harness),'--kind',kind,'--binary',str(binaries[kind]),'--sipp',str(base/'sipp/usr/bin/sipp'),'--rate',str(rate),'--seconds',str(seconds),'--output',str(output)]
  if kind=='opensips': cmd += ['--modules',str(base/'opensips/usr/lib/x86_64-linux-gnu/opensips/modules')]
  if stage=='soak': cmd += ['--idle-seconds','90']
  print('START '+name,flush=True)
  samples=[]; started=time.monotonic()
  with (root/(name+'.driver.log')).open('w') as log:
   proc=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT)
   while proc.poll() is None:
    try:
     children=Path(f'/proc/{proc.pid}/task/{proc.pid}/children').read_text().split()
     for pid in children:
      try:
       args=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
       if str(binaries[kind]).encode() not in args: continue
       status=Path(f'/proc/{pid}/status').read_text().splitlines()
       vals={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in status if ':' in line}
       samples.append({'seconds':round(time.monotonic()-started,3),'pid':int(pid),'rss_kib':int(vals.get('VmRSS','0 kB').split()[0]),'threads':int(vals.get('Threads','0'))})
      except (FileNotFoundError,ProcessLookupError): pass
    except FileNotFoundError: pass
    time.sleep(1)
  (root/(name+'.memory.json')).write_text(json.dumps(samples,indent=2))
  if (output/'result.json').exists():
   result=json.loads((output/'result.json').read_text()); result['run_name']=name; result['stage']=stage
   result['memory_root_process_samples']=samples
   summary.append(result)
   print(json.dumps({'run':name,'exit':proc.returncode,'valid':result['valid'],'caller':result['caller'],'callee':result['callee'],'rtt_ms':result['invite_rtt_ms'],'generator_drops':result['generator_socket_drops']}),flush=True)
  else:
   summary.append({'run_name':name,'stage':stage,'kind':kind,'valid':False,'driver_exit':proc.returncode,'error':'no result.json; see driver log'})
   print('ERROR '+name+' no result.json',flush=True)
  (root/'summary.json').write_text(json.dumps(summary,indent=2))
  if stage=='smoke' and (not summary[-1]['valid']): raise SystemExit('Smoke failed; inspect before sustained runs')
print('SUITE_COMPLETE',flush=True)
