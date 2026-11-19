/**
 * 图片地址与裂图兜底。
 *
 * 三件事都在这:
 * 1. 后端历史数据里有 `\\` 分隔的路径（Windows 上 `os.path.join` 的产物），
 *    浏览器解析不出正确地址 → 统一换成 `/`；
 * 2. 药品图可能来自外部站点（hhyy.com），被防盗链或断网时就是裂图 →
 *    换成本地内联 SVG 占位，不再发请求；
 * 3. 空字符串 / null 直接给占位图，省掉模板里到处写三元表达式。
 */

const PLACEHOLDER_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300">' +
  '<rect width="400" height="300" fill="#fef2f2"/>' +
  '<path d="M160 190h80M200 150v80" stroke="#fca5a5" stroke-width="8" stroke-linecap="round"/>' +
  '<text x="200" y="235" text-anchor="middle" fill="#f87171" font-size="16" font-family="sans-serif">暂无药品图片</text>' +
  '</svg>'

export const FALLBACK_IMAGE = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(PLACEHOLDER_SVG)}`

/** 把后端给的图片地址修正成浏览器能直接用的形式（不做兜底）。 */
export const normalizeImageUrl = (value) => {
  if (typeof value !== 'string') return ''
  return value.trim().replace(/\\/g, '/')
}

/** 直接可用的 src：空值也有占位图，模板里不用再判断。 */
export const imageUrl = (value) => normalizeImageUrl(value) || FALLBACK_IMAGE

/**
 * `<img @error>` 处理器：把裂图换成占位图。
 * 打一个 dataset 标记，占位图万一也加载失败也不会无限替换。
 */
export const onImageError = (event) => {
  const img = event && event.target
  if (!img || img.dataset.fallback === '1') return
  img.dataset.fallback = '1'
  img.src = FALLBACK_IMAGE
}

export default {FALLBACK_IMAGE, imageUrl, normalizeImageUrl, onImageError}
