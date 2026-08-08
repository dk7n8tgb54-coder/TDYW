#!/bin/bash
cd /data/spug/spug_api
python3 manage.py test \
  apps.radio_license.tests.characterization.test_radio_license \
  apps.radio_license.tests.characterization.test_celery_tasks \
  apps.contract_agreement.tests.characterization.test_contract_agreement \
  apps.document.tests.characterization.test_file_folder \
  apps.document.tests.characterization.test_party_building \
  apps.regulation.tests.characterization.test_regulation \
  apps.evidence.tests.characterization.test_evidence_integration \
  --noinput --keepdb 2>&1 | tee /data/spug/spug_api/test_results.txt
