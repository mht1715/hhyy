/**
 * SSE 流解析。
 *
 * 契约里的帧格式是标准的 `event: xxx` + `data: {...}` + 空行，
 * 但真实网络下要额外兜住这些情况：
 * - 换行符可能是 \r\n、\n，甚至单独的 \r
 * - 一次 read() 可能拿到多帧，也可能一帧被拆在两块里
 * - 注释行（以 : 开头，常被用作心跳）必须忽略
 * - 一个事件允许多行 data，按规范用 \n 拼接后再 JSON.parse
 */

/**
 * 把 fetch 的 ReadableStream 解析成 {event, data} 异步迭代器。
 * data 解析失败时降级为 {raw: 原始文本}，不让整条流中断。
 *
 * @param {Response} response
 */
export async function* streamEvents(response) {
  if (!response || !response.body) {
    throw new Error('当前响应不支持流式读取')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')

  let buffer = ''
  let finished = false
  let eventName = ''
  let dataLines = []

  // 空行到达时结算一帧；没有 data 的事件（例如只剩 event 行）直接丢弃
  const flushFrame = () => {
    if (dataLines.length === 0) {
      eventName = ''
      return null
    }

    const text = dataLines.join('\n')
    let data
    try {
      data = JSON.parse(text)
    } catch (e) {
      data = {raw: text}
    }

    const frame = {event: eventName || 'message', data}
    eventName = ''
    dataLines = []
    return frame
  }

  const handleLine = (line) => {
    if (line === '') return flushFrame()
    if (line.startsWith(':')) return null // 注释行 / 心跳

    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    // 规范：冒号后最多吃掉一个空格
    if (value.startsWith(' ')) value = value.slice(1)

    if (field === 'event') {
      eventName = value
    } else if (field === 'data') {
      dataLines.push(value)
    }
    // id / retry 本项目用不到，直接忽略
    return null
  }

  // 从 buffer 里尽可能多地切出完整行；末尾的 \r 要留到下一块确认是不是 \r\n
  function* drainLines() {
    while (true) {
      const lf = buffer.indexOf('\n')
      const cr = buffer.indexOf('\r')
      let index = -1
      let length = 1

      if (cr !== -1 && (lf === -1 || cr < lf)) {
        index = cr
        if (buffer[cr + 1] === '\n') {
          length = 2
        } else if (cr === buffer.length - 1 && !finished) {
          return
        }
      } else if (lf !== -1) {
        index = lf
      } else {
        return
      }

      const line = buffer.slice(0, index)
      buffer = buffer.slice(index + length)
      const frame = handleLine(line)
      if (frame) yield frame
    }
  }

  try {
    while (true) {
      const {value, done} = await reader.read()
      if (done) {
        finished = true
        buffer += decoder.decode()
        break
      }
      buffer += decoder.decode(value, {stream: true})
      yield* drainLines()
    }

    yield* drainLines()

    // 流结束时最后一行可能没有换行符
    if (buffer.length > 0) {
      const frame = handleLine(buffer)
      buffer = ''
      if (frame) yield frame
    }
    // 后端若漏掉末尾空行，这里补发最后一帧，避免丢掉 done
    const lastFrame = flushFrame()
    if (lastFrame) yield lastFrame
  } finally {
    // 消费方可能收到 done 就提前 break，此时主动取消底层流，避免连接悬挂
    if (!finished) {
      try {
        await reader.cancel()
      } catch (e) {
        // abort 之后 cancel 可能抛错，忽略
      }
    }
    try {
      reader.releaseLock()
    } catch (e) {
      // 流已被取消时 releaseLock 可能抛错，忽略
    }
  }
}
