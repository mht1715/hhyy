/**
 * @ 提及相关的纯函数。
 *
 * 只负责文本与光标计算，不碰 DOM / 响应式，方便在输入法与
 * 任意输入框里复用。offset 一律指插入的 `@` 在整段文本中的下标。
 */

const isSpace = (char) => char === undefined || char === null || /\s/.test(char)

/**
 * 判断光标前是否处于一个未完成的 @ 提及。
 * 约束：@ 必须在行首或空白之后，且 @ 到光标之间不能有空白。
 *
 * @param {string} text
 * @param {number} caret
 * @returns {{active: boolean, keyword: string, start: number}}
 */
export function detectMention(text, caret) {
  const value = typeof text === 'string' ? text : ''
  const pos = Number.isInteger(caret) ? Math.min(Math.max(caret, 0), value.length) : value.length
  const before = value.slice(0, pos)
  const at = before.lastIndexOf('@')

  if (at === -1) {
    return {active: false, keyword: '', start: -1}
  }
  // @ 前面必须什么都没有（行首）或者是空白
  if (at > 0 && !isSpace(value[at - 1])) {
    return {active: false, keyword: '', start: -1}
  }

  const keyword = before.slice(at + 1)
  if (/\s/.test(keyword)) {
    return {active: false, keyword: '', start: -1}
  }

  return {active: true, keyword, start: at}
}

/**
 * 按 name / code 做包含匹配（中文无需分词，直接 includes 即可）。
 *
 * @param {Array} candidates
 * @param {string} keyword
 * @returns {Array}
 */
export function filterCandidates(candidates, keyword) {
  const list = Array.isArray(candidates) ? candidates : []
  const query = String(keyword || '').trim().toLowerCase()
  if (!query) return list.slice()

  return list.filter((agent) => {
    if (!agent) return false
    const name = String(agent.name || '').toLowerCase()
    const code = String(agent.code || agent.agent_code || '').toLowerCase()
    return name.includes(query) || code.includes(query)
  })
}

/**
 * 把光标处的 @keyword 替换成 `@Agent 名 `，并返回插入位置。
 *
 * @param {string} text
 * @param {number} caret
 * @param {object} agent
 * @returns {{text: string, caret: number, mention: {agent_code: string, name: string, offset: number}}}
 */
export function insertMention(text, caret, agent) {
  const value = typeof text === 'string' ? text : ''
  const pos = Number.isInteger(caret) ? Math.min(Math.max(caret, 0), value.length) : value.length
  const target = agent || {}
  const name = target.name || target.code || target.agent_code || 'Agent'
  const code = target.agent_code || target.code || ''

  const detected = detectMention(value, pos)
  const start = detected.active ? detected.start : pos

  // 光标可能停在关键词中间，向右吃掉同一个 token 的剩余字符
  let end = pos
  if (detected.active) {
    while (end < value.length && !/\s/.test(value[end])) end += 1
  }

  const before = value.slice(0, start)
  const after = value.slice(end)
  const inserted = `@${name} `

  return {
    text: `${before}${inserted}${after}`,
    caret: start + inserted.length,
    mention: {
      agent_code: code,
      name,
      offset: start
    }
  }
}

/**
 * 输入框内容变化后，过滤掉已经被删掉的 mention。
 *
 * @param {string} text
 * @param {Array} mentions
 * @returns {Array}
 */
export function collectMentions(text, mentions) {
  const value = typeof text === 'string' ? text : ''
  return (Array.isArray(mentions) ? mentions : []).filter((mention) => {
    if (!mention || !mention.name) return false
    return value.includes(`@${mention.name}`)
  })
}
