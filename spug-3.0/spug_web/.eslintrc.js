/**
 * 【任务5.1】ESLint 配置 - 前端代码检查工具
 * 配置强制规则，确保代码质量
 * 
 * 【注意】部分规则设为warn而非error，以兼容历史代码
 */
module.exports = {
  extends: ['react-app'],
  rules: {
    // ==================== 代码风格规则 ====================
    'indent': ['warn', 2, { 'SwitchCase': 1 }],
    'quotes': ['warn', 'single'],
    'semi': ['warn', 'always'],
    'no-trailing-spaces': 'warn',
    'eol-last': ['warn', 'always'],
    'max-len': ['warn', { 
      'code': 120, 
      'ignoreUrls': true,
      'ignoreStrings': true,
      'ignoreTemplateLiterals': true
    }],

    // ==================== 文件和函数行数限制 ====================
    // 文件行数限制（代码检查报告要求 ≤1000行）
    'max-lines': ['error', {
      'max': 1000,
      'skipBlankLines': true,
      'skipComments': true
    }],
    
    // 函数行数限制（设为warn以兼容历史代码）
    'max-lines-per-function': ['warn', {
      'max': 200,
      'skipBlankLines': true,
      'skipComments': true
    }],
    
    // 函数复杂度限制
    'complexity': ['warn', { 'max': 15 }],
    
    // 最大嵌套深度
    'max-depth': ['warn', { 'max': 4 }],

    // ==================== 代码质量规则 ====================
    'no-console': ['warn', { 'allow': ['warn', 'error'] }],
    'no-debugger': 'warn',
    'no-alert': 'warn',
    // 【修改】设为warn以兼容历史代码
    'no-unused-vars': ['warn', { 
      'vars': 'all', 
      'args': 'after-used',
      'ignoreRestSiblings': true
    }],
    'no-undef': 'error',
    'no-unreachable': 'error',
    'no-dupe-keys': 'error',
    'no-dupe-args': 'error',
    'no-duplicate-case': 'error',
    'no-empty': 'warn',
    'no-empty-function': 'warn',
    'no-eval': 'error',
    'no-implied-eval': 'error',
    'no-new-func': 'error',
    // 【修改】MobX store常用模式，设为warn
    'no-return-assign': 'warn',
    'no-return-await': 'warn',
    'require-await': 'warn',

    // ==================== React 相关规则 ====================
    'react/prop-types': 'off',
    'react/no-unused-state': 'warn',
    'react/no-deprecated': 'warn',
    'react/no-direct-mutation-state': 'error',
    'react/no-unsafe': 'warn',
    // 【修改】设为warn以兼容历史代码
    'react/jsx-key': 'warn',
    'react/jsx-no-duplicate-props': 'error',
    'react/jsx-no-target-blank': 'warn',

    // ==================== Hooks 规则 ====================
    'react-hooks/rules-of-hooks': 'error',
    'react-hooks/exhaustive-deps': 'warn',

    // ==================== 导入规则 ====================
    // 【修改】设为warn以兼容历史代码
    'no-duplicate-imports': 'warn',
    'no-unused-expressions': 'warn',
    // 【修改】某些测试文件需要动态导入，设为warn
    'import/first': 'warn',
  },
  overrides: [
    // 对特定文件放宽规则
    {
      files: ['**/*.test.js', '**/*.spec.js', '**/__tests__/**'],
      rules: {
        'max-lines': 'off',
        'max-lines-per-function': 'off',
        'no-console': 'off'
      }
    },
    {
      files: ['**/mocks/**', '**/mock/**'],
      rules: {
        'max-lines': 'off'
      }
    }
  ],
  env: {
    'browser': true,
    'es6': true,
    'node': true,
    'jest': true
  },
  parserOptions: {
    'ecmaVersion': 2020,
    'sourceType': 'module',
    'ecmaFeatures': {
      'jsx': true
    }
  }
};
