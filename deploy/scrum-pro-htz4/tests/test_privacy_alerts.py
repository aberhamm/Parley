import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / 'privacy-alerts.py'
spec = importlib.util.spec_from_file_location('privacy_alerts', SOURCE)
alerts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alerts)
NOW = dt.datetime(2026, 10, 27, 10, tzinfo=dt.timezone.utc)
INSTANCE = '0a79b002-2da8-44ef-88a7-d5403b0429f7'
STAMP = NOW.isoformat().replace('+00:00', 'Z')
JOURNAL = dict(instance_id=INSTANCE, journal_sha256='a'*64, receipt_count=5)


def bundle():
    return dict(host=dict(status=dict(status='ok', exported_at=STAMP, **JOURNAL),
                          services={'logger': True, 'timer': True}, journal=JOURNAL.copy()),
                studio=dict(status=dict(status='ok', sync_status='ok', expiry_status='ok',
                                        nas_mirror=True, last_attempt_at=STAMP,
                                        last_success=dict(host_exported_at=STAMP, local_durable_at=STAMP,
                                                          host_journal_sha256='a'*64, **JOURNAL)),
                            journal=JOURNAL.copy()),
                nas=dict(expiry=dict(status='ok', apply=True, checked_at=STAMP),
                         backup=dict(captured_at=STAMP, size=130000, format='PGDMP'),
                         journal=JOURNAL.copy()))

def config():
    return {'version':1,'checks':{key:'https://health.matthew.systems/ping/0a79b002-2da8-44ef-88a7-'+f'{index:012d}' for index,key in enumerate(alerts.GROUPS)}}


class AlertTests(unittest.TestCase):
    def test_healthy_all_three_groups(self):
        self.assertEqual(alerts.assess(bundle(), INSTANCE, NOW),
                         {'backup': [], 'expiry': [], 'journal': []})

    def test_overdue_missing_corrupt_and_future_backup(self):
        for value in [None, {'captured_at': (NOW-dt.timedelta(hours=31)).isoformat(), 'size': 130000, 'format': 'PGDMP'},
                      {'captured_at': STAMP, 'size': 10, 'format': 'PGDMP'},
                      {'captured_at': STAMP, 'size': 130000, 'format': 'broken'},
                      {'captured_at': (NOW+dt.timedelta(minutes=2)).isoformat(), 'size': 130000, 'format': 'PGDMP'}]:
            with self.subTest(value=value):
                b = bundle(); b['nas']['backup'] = value
                result = alerts.assess(b, INSTANCE, NOW)
                self.assertTrue(result['backup']); self.assertFalse(result['journal'])

    def test_each_expiry_failure_is_visible(self):
        mutations = [lambda b: b['host']['status'].update(status='failed'),
                     lambda b: b['host']['status'].update(exported_at=(NOW-dt.timedelta(minutes=6)).isoformat()),
                     lambda b: b['host']['services'].update(logger=False),
                     lambda b: b['host']['services'].update(timer=False),
                     lambda b: b['nas']['expiry'].update(apply=False),
                     lambda b: b['nas']['expiry'].update(status='failed'),
                     lambda b: b['nas']['expiry'].update(checked_at=(NOW-dt.timedelta(minutes=6)).isoformat()),
                     lambda b: b['studio']['status'].update(expiry_status='failed'),
                     lambda b: b['studio']['status'].update(last_attempt_at=(NOW-dt.timedelta(minutes=6)).isoformat())]
        for mutate in mutations:
            b = bundle(); mutate(b)
            self.assertTrue(alerts.assess(b, INSTANCE, NOW)['expiry'])

    def test_failed_or_stale_sync_and_missing_mirror_fail(self):
        for update in [dict(status='failed'), dict(sync_status='failed'), dict(nas_mirror=False),
                       dict(last_success=None), dict(last_attempt_at='invalid')]:
            b=bundle(); b['studio']['status'].update(update)
            self.assertTrue(alerts.assess(b, INSTANCE, NOW)['journal'])
        b=bundle(); b['studio']['status']['last_success']['host_exported_at']=(NOW-dt.timedelta(minutes=6)).isoformat()
        self.assertTrue(alerts.assess(b, INSTANCE, NOW)['journal'])

    def test_missing_remote_does_not_hide_unrelated_checks(self):
        b=bundle(); b['host']=None
        result=alerts.assess(b,INSTANCE,NOW)
        self.assertTrue(result['expiry']); self.assertTrue(result['journal']); self.assertFalse(result['backup'])
        b=bundle(); b['nas']=None
        self.assertTrue(all(alerts.assess(b,INSTANCE,NOW).values()))

    def test_journal_identity_and_metadata_checks(self):
        for source in ['host','studio','nas']:
            for key,value in [('instance_id','11111111-1111-1111-1111-111111111111'),
                              ('journal_sha256','bad'),('receipt_count',True),('receipt_count',-1)]:
                b=bundle(); b[source]['journal'][key]=value
                self.assertTrue(alerts.assess(b,INSTANCE,NOW)['journal'])

    def test_cumulative_local_copy_may_legitimately_exceed_restored_host(self):
        b=bundle(); b['host']['journal']['receipt_count']=3
        b['host']['journal']['journal_sha256']='b'*64
        b['host']['status'].update(b['host']['journal'])
        b['studio']['status']['last_success']['host_journal_sha256']='b'*64
        self.assertFalse(alerts.assess(b,INSTANCE,NOW)['journal'])

    def test_mirror_mismatch_alerts_after_bounded_propagation_window(self):
        b=bundle(); b['nas']['journal']['journal_sha256']='b'*64
        self.assertEqual(alerts.assess(b,INSTANCE,NOW)['journal'], [])
        old={'journal': {'status': 'pending', 'mismatch_since': {'nas_mirror': (NOW-dt.timedelta(minutes=6)).isoformat()}}}
        self.assertTrue(alerts.assess(b,INSTANCE,NOW,previous=old)['journal'])

    def test_atomic_journal_status_publication_gaps_have_independent_grace(self):
        for name in ['host', 'studio']:
            b=bundle(); b[name]['journal'].update(receipt_count=6, journal_sha256='b'*64)
            if name=='studio': b['nas']['journal'].update(b[name]['journal'])
            self.assertFalse(alerts.assess(b,INSTANCE,NOW)['journal'])
            old={'journal': {'mismatch_since': {name+'_metadata': (NOW-dt.timedelta(minutes=6)).isoformat()}}}
            self.assertTrue(alerts.assess(b,INSTANCE,NOW,previous=old)['journal'])
            unrelated={'journal': {'mismatch_since': {'nas_mirror': (NOW-dt.timedelta(minutes=6)).isoformat()}}}
            self.assertFalse(alerts.assess(b,INSTANCE,NOW,previous=unrelated)['journal'])

    def test_host_advancing_does_not_create_false_sync_alarm(self):
        b=bundle(); b['host']['journal'].update(receipt_count=6,journal_sha256='b'*64)
        b['host']['status'].update(b['host']['journal'])
        self.assertFalse(alerts.assess(b,INSTANCE,NOW)['journal'])

    def test_only_canonical_ping_capabilities_allowed(self):
        valid='https://health.matthew.systems/ping/'+INSTANCE
        self.assertEqual(alerts.ping_url(valid),valid)
        for url in [valid+'?token=x',valid+'#x',valid+'/fail',valid.replace('https:','http:'),
                    valid.replace('health.matthew.systems','other.example'),valid.replace('/ping/','/api/'),
                    valid.replace('health.','user:password@health.')]:
            with self.assertRaises(ValueError): alerts.ping_url(url)

    def test_reports_only_static_codes_and_pings_every_group(self):
        b=bundle(); b['host']=None
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); root.chmod(0o700)
            conf=config()
            sent=[]
            out=alerts.run_once(conf,INSTANCE,root,collector=lambda:b,
                                sender=lambda url,failed,codes:sent.append((failed,codes)),now=NOW)
            self.assertEqual(len(sent),3)
            self.assertEqual(out['checks']['backup']['status'],'ok')
            self.assertEqual(out['checks']['expiry']['status'],'failed')
            raw=(root/'alerts-status.json').read_text()
            self.assertNotIn('https://',raw); self.assertNotIn(INSTANCE,raw)
            self.assertEqual((root/'alerts-status.json').stat().st_mode & 0o777,0o600)

    def test_sender_failure_visible_and_other_pings_continue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); root.chmod(0o700)
            conf=config()
            calls=[]
            def sender(url,failed,codes):
                calls.append(url)
                if len(calls)==1:raise RuntimeError('secret capability must not appear')
            out=alerts.run_once(conf,INSTANCE,root,collector=bundle,sender=sender,now=NOW)
            self.assertEqual(len(calls),3); self.assertEqual(out['status'],'failed')
            self.assertNotIn('secret capability',(root/'alerts-status.json').read_text())

    def test_unwritable_alert_state_cannot_send_green_or_forget_mismatch_timer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); root.chmod(0o700)
            conf=config()
            sender=mock.Mock()
            with mock.patch.object(alerts.studio,'_atomic_json',side_effect=OSError('private write failed')):
                with self.assertRaises(OSError):
                    alerts.run_once(conf,INSTANCE,root,collector=bundle,sender=sender,now=NOW)
            sender.assert_not_called()

    def test_mismatch_timers_persist_then_clear_on_convergence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); root.chmod(0o700)
            conf=config()
            b=bundle(); b['host']['journal'].update(receipt_count=6,journal_sha256='b'*64)
            out=alerts.run_once(conf,INSTANCE,root,collector=lambda:b,sender=lambda *a:None,now=NOW)
            self.assertEqual(out['checks']['journal']['mismatch_since'],{'host_metadata':STAMP})
            out=alerts.run_once(conf,INSTANCE,root,collector=lambda:b,sender=lambda *a:None,now=NOW+dt.timedelta(seconds=301))
            self.assertIn('host_metadata_mismatch_over_5m',out['checks']['journal']['reasons'])
            out=alerts.run_once(conf,INSTANCE,root,collector=bundle,sender=lambda *a:None,now=NOW)
            self.assertNotIn('mismatch_since',out['checks']['journal'])

    def test_duplicate_capabilities_refused_so_fail_cannot_be_overwritten_by_other_group(self):
        bad=config();bad['checks']['expiry']=bad['checks']['backup']
        with self.assertRaises(ValueError):alerts.validate_config(bad)

    def test_clock_is_sampled_after_bounded_remote_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();root.chmod(0o700);collected=[]
            class Clock(dt.datetime):
                @classmethod
                def now(cls, tz=None):
                    self.assertTrue(collected,'clock sampled before potentially slow remote probes')
                    return NOW
            def collector():
                collected.append(True);return bundle()
            with mock.patch.object(alerts.dt,'datetime',Clock):
                out=alerts.run_once(config(),INSTANCE,root,collector=collector,sender=lambda *a:None)
            self.assertEqual(out['status'],'ok')

    def test_read_only_probes_do_not_run_maintenance_or_collect_dump_contents(self):
        for code in [alerts.HOST_PROBE,alerts.NAS_PROBE]:
            compile(code,'probe','exec')
            self.assertNotIn('run_maintenance(',code)
            self.assertNotIn('expire_backups(',code)
            self.assertNotIn('pg_dump',code)
        self.assertIn('O_NOFOLLOW',alerts.NAS_PROBE)
        self.assertIn('read(5)',alerts.NAS_PROBE)

if __name__=='__main__':unittest.main()
