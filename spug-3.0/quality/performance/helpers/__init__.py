"""
Performance testing helpers package.

All locustfiles must import safety check before doing anything else:

    from helpers.safety import check_safety, SafetyLevel
    from helpers.auth import TokenPoolHttpUser
    from helpers.test_data import TestDataGenerator
    from helpers.metrics import MetricsCollector
    from helpers.cleanup import CleanupRegistry
"""

__version__ = "1.0.0"
