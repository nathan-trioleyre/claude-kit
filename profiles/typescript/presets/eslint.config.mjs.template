// @ts-check
import js from '@eslint/js';
import { defineConfig, globalIgnores } from 'eslint/config';
import tseslint from 'typescript-eslint';

export default defineConfig(
  globalIgnores(['dist/**', 'build/**', 'coverage/**', 'node_modules/**']),
  js.configs.recommended,
  {
    files: ['**/*.{ts,tsx,mts,cts}'],
    extends: [...tseslint.configs.strictTypeChecked],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      complexity: ['warn', 12],
      'max-depth': ['warn', 4],
      'no-eval': 'error',
      'no-implied-eval': 'error',
    },
  },
  {
    files: ['**/*.{js,mjs,cjs}'],
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      complexity: ['warn', 12],
      'max-depth': ['warn', 4],
      'no-eval': 'error',
      'no-implied-eval': 'error',
    },
  },
);
