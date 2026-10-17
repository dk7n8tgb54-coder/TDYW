async (page) => {
  const fs = require('fs');
  const dotenv = require('E:/TDYW/spug-3.0/quality/e2e/node_modules/dotenv');
  const env = dotenv.parse(fs.readFileSync('E:/TDYW/spug-3.0/quality/e2e/.env'));
  const response = await page.request.post('http://localhost:8080/api/account/login/', {
    data: {
      username: env.E2E_TEST_USERNAME || 'e2e_tester',
      password: env.E2E_TEST_PASSWORD,
      type: 'default',
    },
  });
  const body = await response.json();
  if (body.error || !body.data?.access_token) throw new Error('Test login failed');
  await page.evaluate(d => {
    sessionStorage.setItem('token', d.access_token);
    sessionStorage.setItem('id', String(d.id));
    sessionStorage.setItem('nickname', d.nickname);
    sessionStorage.setItem('is_supper', String(d.is_supper));
    sessionStorage.setItem('tenant_id', d.tenant_id || 'admin');
  }, body.data);
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto('http://localhost:8080/upgrade');
}
