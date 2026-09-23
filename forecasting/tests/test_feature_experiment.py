from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from forecasting.baseline import Example
from forecasting.experiment_features import FeatureRow, feature_values, training_rows
from forecasting.feature_weather import PROFILE, UNITS, fetch_feature_run, parse_feature_run
from forecasting.sites import SITES
from forecasting.storage import write_json
from forecasting.weather import MODEL, SOURCE, UTC


class FeatureArchiveTests(unittest.TestCase):
    def setUp(self):
        self.initialized = datetime(2026, 1, 1, tzinfo=UTC)
        response = {'latitude':43.6, 'longitude':78.5, 'utc_offset_seconds':0,
                    'hourly_units':{'time':'iso8601', **UNITS},
                    'hourly':{'time':[(self.initialized+timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M')
                                      for i in range(24)]}}
        for field,value in {'wind_speed_100m':8., 'wind_speed_10m':5., 'wind_direction_100m':90.,
                            'temperature_2m':-10., 'surface_pressure':950.}.items():
            response['hourly'][field] = [value] * 24
        self.payload = {'source':SOURCE,'model':MODEL,'feature_profile':PROFILE,
                        'requested_variables':list(UNITS),'site_ids':list(SITES),
                        'initialized_at':self.initialized.isoformat(),
                        'usable_after_at':(self.initialized+timedelta(hours=12)).isoformat(),
                        'responses':[copy.deepcopy(response) for _ in SITES]}

    def test_features_use_same_historical_run(self):
        run = parse_feature_run(self.payload, self.initialized)
        issued = self.initialized+timedelta(hours=12)
        features=feature_values(run,'turbine_1',issued,issued+timedelta(hours=1))
        self.assertAlmostEqual(features['direction_sin'],1)
        self.assertAlmostEqual(features['direction_cos'],0)
        self.assertEqual(features['wind_shear'],3)
        self.assertEqual(features['wind_mean_3h'],8)
        self.assertEqual(features['wind_ramp_3h'],0)
        self.assertEqual(features['forecast_lead_hours'],13)
        with self.assertRaises(ValueError):
            feature_values(run,'turbine_1',issued-timedelta(hours=1),issued)
        with self.assertRaises(ValueError):
            feature_values(run,'turbine_1',issued,issued)

    def test_missing_weather_is_not_imputed(self):
        self.payload['responses'][0]['hourly']['temperature_2m'][13]=None
        run=parse_feature_run(self.payload,self.initialized)
        issued=self.initialized+timedelta(hours=12)
        with self.assertRaises(KeyError):
            feature_values(run,'turbine_1',issued,issued+timedelta(hours=1))

    def test_invalid_units_values_and_profile_are_rejected(self):
        payload=copy.deepcopy(self.payload)
        payload['feature_profile']='incompatible'
        with self.assertRaises(ValueError):
            parse_feature_run(payload,self.initialized)
        for field,value in [('wind_direction_100m',361),('surface_pressure',0),
                            ('temperature_2m',float('nan')),('wind_speed_10m',-1)]:
            with self.subTest(field=field):
                payload=copy.deepcopy(self.payload)
                payload['responses'][0]['hourly'][field][0]=value
                with self.assertRaises(ValueError):
                    parse_feature_run(payload,self.initialized)
        self.payload['responses'][0]['hourly_units']['surface_pressure']='Pa'
        with self.assertRaises(ValueError):
            parse_feature_run(self.payload,self.initialized)

    def test_default_is_offline_and_cache_is_reusable(self):
        with tempfile.TemporaryDirectory() as directory:
            cache=Path(directory)
            with patch('forecasting.feature_weather.urlopen',side_effect=AssertionError('Network forbidden')):
                with self.assertRaises(FileNotFoundError):
                    fetch_feature_run(self.initialized,cache)
                write_json(cache/'ecmwf_ifs_20260101T0000Z.json',self.payload)
                self.assertEqual(len(fetch_feature_run(self.initialized,cache).points['turbine_1']),24)

    def test_training_excludes_labels_at_or_after_cutoff_and_long_leads(self):
        cutoff=self.initialized
        issued=cutoff-timedelta(hours=24)
        def row(target):
            return FeatureRow(Example('turbine_1',issued,target,8,.5),{})
        eligible=row(cutoff-timedelta(hours=1))
        rows=[eligible,row(cutoff),row(cutoff+timedelta(hours=1)),
              FeatureRow(Example('turbine_1',issued-timedelta(hours=24),
                                 cutoff-timedelta(hours=1),8,.5),{})]
        self.assertEqual(training_rows(rows,'turbine_1',cutoff),[eligible])


if __name__=='__main__':
    unittest.main()
