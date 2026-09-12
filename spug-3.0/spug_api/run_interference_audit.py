"""干扰模块只读健康检查。

该脚本用于发布前快速确认最终模型和关键不变量，行为测试位于
``apps.interference.tests``，不通过读取源码来伪造测试。
"""

import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.interference.models import (  # noqa: E402
    AirInterferenceDetail,
    GroundInterferenceDetail,
    InvestigationEvent,
    InterferenceEvent,
    InterferenceInvestigation,
    SpectrumMeasurement,
)


def main():
    models = (
        InterferenceEvent,
        GroundInterferenceDetail,
        AirInterferenceDetail,
        InterferenceInvestigation,
        InvestigationEvent,
        SpectrumMeasurement,
    )
    print('Interference final model audit')
    for model in models:
        print(f'{model.__name__}: {model.objects.count()} active records')
    invalid_ground = GroundInterferenceDetail.objects.exclude(
        event__scene_code__in=('ground', 'cross'))
    invalid_air = AirInterferenceDetail.objects.exclude(
        event__scene_code__in=('air', 'cross'))
    print(f'invalid ground details: {invalid_ground.count()}')
    print(f'invalid air details: {invalid_air.count()}')
    return 0 if not invalid_ground.exists() and not invalid_air.exists() else 1


if __name__ == '__main__':
    raise SystemExit(main())
