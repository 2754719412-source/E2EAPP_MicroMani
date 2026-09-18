import { fileURLToPath } from 'node:url'
import baseConfig from '../../frontend/vite.config.ts'

// 独立审查配置：复现已发现的问题，不加入项目默认测试集合。
export default {
  ...baseConfig,
  root: fileURLToPath(new URL('../../frontend', import.meta.url)),
  test: {
    ...baseConfig.test,
    include: [fileURLToPath(new URL('../../frontend/output/ui-redesign/review-settings.audit.tsx', import.meta.url))],
  },
}
