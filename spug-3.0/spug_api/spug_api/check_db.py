from django.conf import settings
db = settings.DATABASES['default']
print(f"HOST={db.get('HOST')}")
print(f"PORT={db.get('PORT')}")
print(f"USER={db.get('USER')}")
print(f"NAME={db.get('NAME')}")
