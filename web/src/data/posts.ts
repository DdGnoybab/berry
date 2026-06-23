// 文章数据 —— 改这里就能在 About 页面的 Posts 列表里加/减文章
// 写新文章：复制一个对象，改 slug / title / excerpt / date / body 即可。
// body 是 markdown 字符串，会用 react-markdown + remark-gfm 渲染。

export type PostCategory = 'tech' | 'life' | 'note'

export interface Post {
  readonly slug: string
  readonly title: string
  /** 列表卡片上的副标题（一两句话） */
  readonly excerpt: string
  /** ISO 日期字符串（YYYY-MM-DD） */
  readonly date: string
  readonly category: PostCategory
  /** 标签（用于切角 chip 展示） */
  readonly tags: readonly string[]
  /** markdown 正文 */
  readonly body: string
}

export const posts: readonly Post[] = [
  {
    slug: 'hello-world',
    title: 'Hello, Berry',
    excerpt: '把项目结构、动机、接下来想做的事都摆在这里，方便自己回头看。',
    date: '2026-06-21',
    category: 'note',
    tags: ['meta', 'berry'],
    body: `## 为什么做 Berry

我想要一个**真正属于自己**的 AI 工作台 —— 不是 ChatGPT 那种对话式工具，也不是 Cursor 那种只面向编码的 IDE，而是能跨场景（学习 / 工作 / 折腾）持续用下去的东西。

飞书是入口（手机 / 电脑都能用），runtime 在自己机器上跑，模型走各家 API。

## 架构

- **Channel 层**：飞书 WebSocket 长连 + 卡片交互
- **Core 层**：LangGraph turn loop + 工具分发 + 审批
- **Skill 层**：用 markdown 写业务 prompt，新增场景 = 新增一个 SKILL.md

## 接下来的事

- 上下文压缩（防 token 爆）
- Cost / Usage 跟踪
- Redis 分布式锁
- 接入 Langfuse 看 trace

慢慢来。`,
  },
  {
    slug: 'gateway-design',
    title: '大模型网关的 4 个核心问题',
    excerpt: '限流、路由、计费、可观测性 —— 给一个统一入口的代价。',
    date: '2026-06-15',
    category: 'tech',
    tags: ['gateway', 'infra', 'interview'],
    body: `## 为什么需要网关

直接调各家模型 API 有几个问题：

1. **限流** —— 不同 provider 的 RPM / TPM 限制不一样，要在网关层做 token bucket
2. **路由** —— 一个请求可能落到不同模型（按成本 / 延迟 / 能力）
3. **计费** —— 跟踪每个用户 / 每个 session 的 token 用量和费用
4. **可观测性** —— 一条 trace 跨多个 provider，需要统一打点

## 限流

最简单的方案是 **token bucket**：

- 每秒补充 N 个 token
- 桶满时拒绝请求
- 支持按 user / model / api-key 多维度独立桶

更高级一点会做 **滑动窗口**（更准确）或 **自适应限流**（根据后端 latency 动态调整）。

## 流式响应

SSE（Server-Sent Events）是最常见的选择，比 WebSocket 简单，比长轮询实时。

注意几个坑：

- 代理 / 网关对 SSE 的缓冲要关掉
- 客户端要处理断连 + 重连
- 错误处理：中途失败不能只断开，要给一个完整的 chunk 让前端知道

## 下一步

- 写一个 toy gateway（FastAPI + Redis）练手
- 看 LiteLLM / OpenRouter 怎么实现的
- 准备面试`,
  },
  {
    slug: 'leetcode-rotate',
    title: '旋转矩阵：从图上画到代码里',
    excerpt: 'LeetCode 48 题。一开始靠"转 4 圈"的直觉写，写完才发现有更干净的解法。',
    date: '2026-06-10',
    category: 'tech',
    tags: ['leetcode', 'array'],
    body: `## 题目

把一个 n × n 矩阵原地顺时针旋转 90°。

## 朴素解法

新建一个矩阵 \`b[j][n-1-i] = a[i][j]\`。

时间 O(n²) 空间 O(n²) —— 不满足"原地"。

## 原地解法

分两步：

1. 沿主对角线翻转（\`a[i][j] ↔ a[j][i]\`）
2. 沿垂直中线翻转（\`a[i][j] ↔ a[i][n-1-j]\`）

两次 O(n²) 翻转就完成了，比"4 圈轮换"清晰多了。

## 关键洞察

矩阵变换常常可以**拆成多个对称操作**。比起直接想"每个元素去哪"，先想"两个轴翻转"这种基础操作，组合起来更不容易出错。

## 边界

- n = 0 / 1：直接返回
- 不用管 n 是奇数还是偶数（对角线 / 中线都通用）`,
  },
]

/** 按日期倒序（最新在前） */
export const sortedPosts: readonly Post[] = [...posts].sort((a, b) =>
  b.date.localeCompare(a.date),
)

export function getPostBySlug(slug: string): Post | null {
  return posts.find((p) => p.slug === slug) ?? null
}
