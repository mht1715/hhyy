import {defineConfig} from 'vite'
import vue from '@vitejs/plugin-vue'
import {VitePWA} from 'vite-plugin-pwa'
// 站点信息（标题 / 描述 / PWA 名称 / 主题色）只在 src/config/site.js 里维护，
// 这里 import 它的原因是 PWA manifest 与 index.html 都得在构建期就知道这些值。
import {siteConfig} from './src/config/site.js'

// 插进 HTML 属性的值要转义，否则描述里出现引号会把 meta 标签截断
const escapeHtml = (value) => String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')

/**
 * 把 index.html 里的 %SITE_*% 换成 site.js 的值（dev 与 build 走同一条管线）。
 *
 * `order: 'post'` 是必须的：vite-plugin-pwa 也会改写 index.html（插 <link rel="manifest">），
 * 它拿到的还是带占位符的原文，谁最后写谁说了算——不排到最后，替换结果会被它覆盖掉。
 */
const siteMeta = () => ({
    name: 'hhyy-site-meta',
    transformIndexHtml: {
        order: 'post',
        handler(html) {
            const values = {
                SITE_LANG: siteConfig.lang,
                SITE_TITLE: siteConfig.fullName,
                SITE_DESC: siteConfig.description,
                SITE_KEYWORDS: siteConfig.keywords.join(','),
                SITE_THEME: siteConfig.themeColor
            }
            // 注意别写成 /%SITE_([A-Z_]+)%/ 再多加一次前缀：那样捕获组拿到的是 TITLE 而不是 SITE_TITLE，
            // 查表永远落空，占位符会原样留在页面里（排查过一次，记在这）
            const replaced = html.replace(/%SITE_[A-Z_]+%/g, (raw) => {
                const key = raw.slice(1, -1)
                return key in values ? escapeHtml(values[key]) : raw
            })
            return replaced
        }
    }
})

export default defineConfig({
    plugins: [
        vue(),
        siteMeta(),
        VitePWA({
            registerType: 'autoUpdate',
            includeAssets: ['favicon.ico', 'apple-touch-icon.png', 'mask-icon.svg'],
            manifest: {
                name: siteConfig.fullName,
                short_name: siteConfig.shortName,
                description: siteConfig.description,
                lang: siteConfig.lang,
                theme_color: siteConfig.themeColor,
                background_color: siteConfig.backgroundColor,
                display: 'standalone',
                orientation: 'portrait',
                scope: '/',
                start_url: '/',
                icons: [
                    {
                        src: 'pwa-192x192.png',
                        sizes: '192x192',
                        type: 'image/png'
                    },
                    {
                        src: 'pwa-512x512.png',
                        sizes: '512x512',
                        type: 'image/png'
                    },
                    {
                        src: 'pwa-512x512.png',
                        sizes: '512x512',
                        type: 'image/png',
                        purpose: 'any maskable'
                    }
                ]
            },
            workbox: {
                globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
                runtimeCaching: [
                    {
                        urlPattern: /^https:\/\/api\./i,
                        handler: 'NetworkFirst',
                        options: {
                            cacheName: 'api-cache',
                            networkTimeoutSeconds: 10,
                            expiration: {
                                maxEntries: 50,
                                maxAgeSeconds: 60 * 60 * 24
                            }
                        }
                    }
                ]
            }
        })
    ],
    server: {
        port: 5173,
        proxy: {
            '/api': {
                target: 'http://localhost:8000',
                changeOrigin: true
            },
            // 静态资源（上传的药品图片、知识库原文件）同样走后端
            '/static': {
                target: 'http://localhost:8000',
                changeOrigin: true
            },
            // 人工客服 WebSocket：必须开 ws:true，否则浏览器连不上坐席通道
            '/ws': {
                target: 'ws://localhost:8000',
                changeOrigin: true,
                ws: true
            }
        }
    }
})
