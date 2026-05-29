#!/usr/bin/env python3
import json

class ParseError(BaseException):
    def __init__(self, message):
        self.message = message

class AttrDict(dict):
    def __setattr__(self, key, value):
        self[key] = value
    def __getattr__(self, item):
        return self.get(item)

class Argument:
    def __init__(self, name, default=None, handler=None, required=True, type=str, filter=None, help=None):
        self.name = name
        self.default = default
        self.type = type
        self.required = required
        self.filter = filter
        self.help = help
        self.handler = handler

    def parse(self, has_key, value):
        if not has_key:
            if self.required and self.default is None:
                raise ParseError(self.help or 'Required Error: %s is required' % self.name)
            else:
                return self.default
        elif value in [u'', '', None]:
            if self.default is not None:
                return self.default
            elif self.required:
                raise ParseError(self.help or 'Value Error: %s must not be null' % self.name)
            elif self.help:
                raise ParseError(self.help)
            else:
                return value
        try:
            if self.type:
                if self.type in (list, dict) and isinstance(value, str):
                    value = json.loads(value)
                    assert isinstance(value, self.type)
                elif self.type == bool and isinstance(value, str):
                    assert value.lower() in ['true', 'false']
                    value = value.lower() == 'true'
                elif not isinstance(value, self.type):
                    value = self.type(value)
        except (TypeError, ValueError, AssertionError):
            raise ParseError(self.help or 'Type Error: %s type must be %s' % (self.name, self.type))
        return value

class BaseParser:
    def __init__(self, *args):
        self.args = []
        for e in args:
            if isinstance(e, str):
                e = Argument(e)
            elif not isinstance(e, Argument):
                raise TypeError('%r is not instance of Argument' % e)
            self.args.append(e)

    def parse(self, data=None, clear=False):
        rst = AttrDict()
        try:
            self._init(data)
            for e in self.args:
                has_key, value = self._get(e.name)
                if clear and has_key is False and e.required is False:
                    continue
                rst[e.name] = e.parse(has_key, value)
        except ParseError as err:
            return None, err.message
        return rst, None

class JsonParser(BaseParser):
    def __init__(self, *args):
        self.__data = None
        super().__init__(*args)

    def _get(self, key):
        return key in self.__data, self.__data.get(key)

    def _init(self, data):
        try:
            if isinstance(data, (str, bytes)):
                if isinstance(data, bytes):
                    data = data.decode('utf-8')
                self.__data = json.loads(data) if data else {}
            else:
                assert hasattr(data, '__contains__')
                assert hasattr(data, 'get')
                assert callable(data.get)
                self.__data = data
        except (ValueError, AssertionError) as e:
            raise ParseError('Invalid data type for parse')

# 测试
test_data = b'{"username":"admin","password":"spug"}'
print(f'Testing with: {test_data}')
form, error = JsonParser(
    Argument('username', help='请输入用户名'),
    Argument('password', help='请输入密码'),
    Argument('captcha', required=False),
    Argument('type', required=False)
).parse(test_data)
print(f'Result: form={dict(form) if form else None}, error={error}')
