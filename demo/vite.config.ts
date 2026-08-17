import { defineConfig } from 'vite';

// Vite 配置：
// - 端口固定 5180，方便与服务端 15231 区分
// - --open 由 npm script 传入，自动打开浏览器
// - SDK 通过 file: 协议作为依赖引入，Vite 会预打包
export default defineConfig({
  server: {
    host: '127.0.0.1',
    port: 5180,
    strictPort: true,
    open: '/',
  },
  preview: {
    host: '127.0.0.1',
    port: 5180,
    strictPort: true,
    open: '/',
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});
