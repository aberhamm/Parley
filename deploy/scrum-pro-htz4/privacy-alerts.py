#!/usr/bin/env python3
"""Read-only Scrum protection checks with independently monitored heartbeats."""
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import sys
import urllib.error
import urllib.request
import urllib.parse

RUNTIME = Path('/Users/matthew/.local/share/scrum-pro-privacy')
GROUPS = ('backup', 'expiry', 'journal')
UTC = dt.timezone.utc
FRESH_SECONDS = 300
BACKUP_SECONDS = 30 * 60 * 60

spec = importlib.util.spec_from_file_location('scrum_studio_for_alerts', Path(__file__).with_name('privacy-studio.py'))
studio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(studio)
privacy = studio.privacy

HOST_PROBE = r'''
import runpy,json,hashlib,pathlib,subprocess
m=runpy.run_path('/opt/apps/scrum-pro/privacy/privacy-host.py')
p=m['maintenance'];root=pathlib.Path('/opt/apps/scrum-pro/privacy')
def journal():
 path=root/'journal/deletions.json';data=p.read_journal(path)
 return dict(instance_id=data['instance_id'],receipt_count=len(data['deletions']),journal_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
status=p.read_private_json(root/'status.json')
services={name:subprocess.run(['/usr/bin/systemctl','is-active','--quiet',unit],timeout=5).returncode==0 for name,unit in [('logger','scrum-pro-logging.service'),('timer','scrum-pro-privacy-maintenance.timer')]}
print(json.dumps(dict(status=status,services=services,journal=journal())))
'''

NAS_PROBE = r'''
import runpy,json,hashlib,pathlib,os,datetime as dt
m=runpy.run_path('/volume1/backups/scrum-pro-privacy/privacy-nas.py')
p=m['load_maintenance'](m['CUSTODY']/'privacy-maintenance.py')
root=m['private_directory'](m['BACKUP_ROOT']);custody=m['private_directory'](m['CUSTODY'])
result={}
try:result['expiry']=p.read_private_json(custody/'expiry-status.json')
except Exception:result['expiry']=None
try:
 path=custody/'journal/deletions.json';j=p.read_journal(path)
 result['journal']=dict(instance_id=j['instance_id'],receipt_count=len(j['deletions']),journal_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
except Exception:result['journal']=None
try:
 names=sorted(os.listdir(root));assert len(names)<=10000
 newest=None
 for name in names:
  if not m['snapshot_name'](name):continue
  folder=m['private_directory'](root/name);path=folder/'scrum-pro-parley.dump'
  if not path.exists() and not path.is_symlink():continue
  # The final container-state artifact is written after dumps/config checks.
  marker=folder/'docker-ps.txt'
  if not marker.exists():continue
  m['check_file'](marker.lstat());assert marker.stat().st_size>0
  fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
  with os.fdopen(fd,'rb') as stream:
   info=os.fstat(stream.fileno());m['check_file'](info)
   assert info.st_size>=1024 and stream.read(5)==b'PGDMP'
   candidate=dict(captured_at=dt.datetime.fromtimestamp(info.st_mtime,dt.timezone.utc).isoformat(),size=info.st_size,format='PGDMP')
  if newest is None or info.st_mtime>newest[0]:newest=(info.st_mtime,candidate)
 result['backup']=newest[1] if newest else None
except Exception:result['backup']=None
print(json.dumps(result))
'''


def fresh(value, now, maximum=FRESH_SECONDS):
    try:
        seconds = (now - privacy.timestamp(value)).total_seconds()
        return -60 <= seconds <= maximum
    except (ValueError, TypeError):
        return False


def journal_valid(data, instance):
    return (isinstance(data, dict) and data.get('instance_id') == instance
            and isinstance(data.get('journal_sha256'), str)
            and re.fullmatch('[0-9a-f]{64}', data['journal_sha256']) is not None
            and type(data.get('receipt_count')) is int and 0 <= data['receipt_count'] <= privacy.MAX_RECORDS)


def mismatch_flags(bundle):
    host, local, nas = [(bundle.get(k) or {}) for k in ['host', 'studio', 'nas']]
    keys = ['instance_id', 'journal_sha256', 'receipt_count']
    success = (local.get('status') or {}).get('last_success') or {}
    return dict(studio_metadata=local.get('journal') != {k: success.get(k) for k in keys},
                host_metadata=host.get('journal') != {k: (host.get('status') or {}).get(k) for k in keys},
                nas_mirror=local.get('journal') != nas.get('journal'))


def assess(bundle, instance, now, previous=None):
    """Return fixed codes only. Normal host-to-offhost propagation is allowed."""
    findings = {key: [] for key in GROUPS}
    host, local, nas = [(bundle.get(k) or {}) for k in ['host', 'studio', 'nas']]
    backup = nas.get('backup') or {}
    if (not fresh(backup.get('captured_at'), now, BACKUP_SECONDS)
            or type(backup.get('size')) is not int or backup['size'] < 1024 or backup.get('format') != 'PGDMP'):
        findings['backup'].append('nightly_backup_missing_invalid_or_over_30h')
    status = host.get('status') or {}
    if status.get('status') != 'ok' or not fresh(status.get('exported_at'), now):
        findings['expiry'].append('host_maintenance_failed_or_stale')
    if host.get('services') != {'logger': True, 'timer': True}:
        findings['expiry'].append('host_logger_or_timer_stopped')
    expiry = nas.get('expiry') or {}
    if expiry.get('status') != 'ok' or expiry.get('apply') is not True or not fresh(expiry.get('checked_at'), now):
        findings['expiry'].append('nas_expiry_failed_or_stale')
    local_status = local.get('status') or {}
    if local_status.get('expiry_status') != 'ok' or not fresh(local_status.get('last_attempt_at'), now):
        findings['expiry'].append('studio_expiry_failed_or_stale')
    success = local_status.get('last_success') or {}
    if (local_status.get('status') != 'ok' or local_status.get('sync_status') != 'ok'
            or local_status.get('nas_mirror') is not True
            or not fresh(local_status.get('last_attempt_at'), now)
            or not fresh(success.get('host_exported_at'), now)
            or not fresh(success.get('local_durable_at'), now)):
        findings['journal'].append('offhost_sync_failed_or_stale')
    if status.get('status') != 'ok' or not fresh(status.get('exported_at'), now):
        findings['journal'].append('host_export_failed_or_stale')
    for label, source in [('host', host), ('studio', local), ('nas', nas)]:
        if not journal_valid(source.get('journal'), instance):
            findings['journal'].append(label + '_journal_missing_invalid_or_wrong_instance')
    # An older restored host can legitimately have fewer receipts. The local
    # cumulative copy must never be required to truncate itself to match it.
    if not journal_valid(success, instance):
        findings['journal'].append('studio_sync_metadata_invalid_or_wrong_instance')
    if not journal_valid(status, instance):
        findings['journal'].append('host_export_metadata_invalid_or_wrong_instance')
    # The writers publish journal and status as separate atomic files, and NAS
    # acknowledgment follows the local write. Each legitimate publication gap
    # gets its own bounded timer; an older unrelated mismatch cannot page it.
    since = ((previous or {}).get('journal') or {}).get('mismatch_since', {})
    if not isinstance(since, dict):
        since = {}
    for name, mismatch in mismatch_flags(bundle).items():
        if mismatch and name in since and not fresh(since[name], now):
            findings['journal'].append(name + '_mismatch_over_5m')
    return findings


def ping_url(value):
    if not isinstance(value, str):
        raise ValueError('invalid alert configuration')
    url = urllib.parse.urlsplit(value)
    if (url.scheme != 'https' or url.netloc != 'health.matthew.systems'
            or url.query or url.fragment or not url.path.startswith('/ping/')):
        raise ValueError('invalid alert configuration')
    privacy.identifier(url.path.removeprefix('/ping/'))
    return value


def validate_config(config):
    privacy.exact_keys(config, {'version', 'checks'}, 'alerts')
    if type(config['version']) is not int or config['version'] != 1:
        raise ValueError('invalid alert configuration')
    privacy.exact_keys(config['checks'], set(GROUPS), 'alert checks')
    for value in config['checks'].values():
        ping_url(value)
    if len(set(config['checks'].values())) != len(GROUPS):
        raise ValueError('alert capabilities must be distinct')
    return config


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('alert delivery redirected')


def send_ping(url, failed, codes):
    url = ping_url(url) + ('/fail' if failed else '')
    request = urllib.request.Request(url, data=('Scrum Pro: ' + (', '.join(codes) if codes else 'checks passed')).encode(),
                                     headers={'User-Agent': 'Mozilla/5.0 (compatible; scrum-pro-protection/1.0)',
                                              'Content-Type': 'text/plain'}, method='POST')
    with urllib.request.build_opener(NoRedirect).open(request, timeout=10) as response:
        if response.status != 200 or len(response.read(4097)) > 4096:
            raise ValueError('alert delivery failed')


def collect(settings):
    bundle = {}
    for name, target, prefix, code in [('host', 'root@htz-4g-nbg', 'python3', HOST_PROBE),
                                        ('nas', settings['nas_mirror']['target'], '/usr/bin/sudo -n /usr/bin/python3', NAS_PROBE)]:
        try:
            raw = studio._ssh_bytes(target, prefix + ' -c ' + shlex.quote(code), limit=256*1024)
            bundle[name] = privacy.decode_json(raw)
        except Exception:
            bundle[name] = None
    try:
        status = privacy.read_private_json(RUNTIME / 'status.json')
        path = RUNTIME / 'journal/deletions.json'
        data = privacy.read_journal(path)
        bundle['studio'] = dict(status=status, journal=dict(instance_id=data['instance_id'], receipt_count=len(data['deletions']),
                                                            journal_sha256=hashlib.sha256(studio._private_bytes(path)).hexdigest()))
    except Exception:
        bundle['studio'] = None
    return bundle


def run_once(config, instance, runtime=RUNTIME, *, collector, sender=send_ping, now=None):
    validate_config(config)
    privacy.identifier(instance)
    runtime = privacy.private_directory(runtime)
    with privacy.directory_lock(runtime, '.privacy-alerts.lock'):
        path = runtime / 'alerts-status.json'
        previous = privacy.read_private_json(path).get('checks', {}) if path.exists() else {}
        try:
            bundle = collector()
        except Exception:
            bundle = {}
        now = now or dt.datetime.now(UTC)
        try:
            findings = assess(bundle, instance, now, previous=previous)
        except Exception:
            findings = {key: ['protection_metadata_invalid'] for key in GROUPS}
        checks = {}
        for key in GROUPS:
            codes = findings[key]
            entry = dict(status='failed' if codes else 'ok', reasons=codes, delivered=False)
            if key == 'journal':
                try:
                    flags = mismatch_flags(bundle)
                except Exception:
                    flags = {}
                old = (previous.get(key) or {}).get('mismatch_since', {})
                if not isinstance(old, dict):
                    old = {}
                times = {name: old.get(name) or privacy.utc_string(now) for name, active in flags.items() if active}
                if times:
                    entry['mismatch_since'] = times
                    if not codes:
                        entry['status'] = 'pending'
            checks[key] = entry
        # Save divergence clocks before any heartbeat. If custody cannot be
        # written, sending green would conceal a checker that forgets every
        # prior mismatch. Independent missed-heartbeat alerts cover that case.
        status = dict(version=1, checked_at=privacy.utc_string(now), status='pending', checks=checks)
        studio._atomic_json(path, status)
        for key, entry in checks.items():
            try:
                sender(config['checks'][key], bool(entry['reasons']), entry['reasons'])
                entry['delivered'] = True
            except Exception:
                entry['delivery_error'] = 'healthchecks_delivery_failed'
        if all(c['delivered'] and c['status'] == 'ok' for c in checks.values()):
            status['status'] = 'ok'
        elif all(c['delivered'] and c['status'] in {'ok', 'pending'} for c in checks.values()):
            status['status'] = 'pending'
        else:
            status['status'] = 'failed'
        studio._atomic_json(path, status)
        return status


def main():
    try:
        config = validate_config(privacy.read_private_json(RUNTIME / 'alerts.json'))
        settings = studio.validate_config(privacy.read_private_json(RUNTIME / 'config.json'))
        result = run_once(config, settings['instance_id'], collector=lambda: collect(settings))
        return 0 if result['status'] in {'ok', 'pending'} else 1
    except Exception:
        # Failed/missing credentials or a crashed checker send no green ping:
        # independent Healthchecks deadlines then raise missed-run alerts.
        print('Scrum Pro protection checker failed; inspect private status.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
