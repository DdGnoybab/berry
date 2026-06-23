// 个人介绍数据 —— 改这里就能改右上角 ABOUT 页面显示的内容
// 设计原则：保持类型简单、字段名稳定；新增字段时请同步更新 Profile 组件。

export interface ProfileLink {
  readonly label: string
  readonly href: string
}

export interface Profile {
  /** 站点头部大字（Z 字距的显示名） */
  readonly brand: string
  /** 自我介绍（一句话定位） */
  readonly tagline: string
  /** 个人简介（多段） */
  readonly bio: readonly string[]
  /** 当前在做的事（短句列表） */
  readonly now: readonly string[]
  /** 技能标签（用于切角 chip 展示） */
  readonly skills: readonly string[]
  /** 联系方式 / 外部链接 */
  readonly links: readonly ProfileLink[]
}

export const profile: Profile = {
  brand: 'BBB',
  tagline: '后端开发 → AI Infra · 在飞书上搭自己的 AI 工作台',
  bio: [
    '这里记录我做的东西、踩过的坑、和一些零碎的想法。',
    '主要在做大模型网关方向，对限流、调度、流式响应这些基础设施问题特别感兴趣。',
    '代码、写作、动手折腾 —— 比起想清楚再动，我更愿意先跑起来再改。',
  ],
  now: [
    'Berry —— 飞书原生的 AI 助手 runtime',
    '准备 MiniMax 大模型网关岗面试',
    '每天一道 LeetCode（栈 / 数组 / 链表轮换）',
  ],
  skills: [
    'Python',
    'FastAPI',
    'PostgreSQL',
    'LangGraph',
    'React',
    'TypeScript',
    'Docker',
    '飞书 / lark-oapi',
  ],
  links: [
    { label: 'GitHub', href: 'https://github.com/' },
    { label: 'Email', href: 'mailto:' },
  ],
}
