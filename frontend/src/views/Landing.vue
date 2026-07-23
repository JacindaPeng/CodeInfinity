<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const highlights = [
  {
    kind: '问答',
    badge: '精选',
    title: '课程问答：带着出处回答，而不是凭空编造',
    excerpt:
      '从 PPT、PDF、Word 与视频字幕中检索相关片段，流式生成回答，并附上章节与资料来源，方便学生回头对照。',
    source: 'RAG 检索',
    time: '实时',
  },
  {
    kind: '考核',
    badge: '精选',
    title: '章节考核：组卷、评分、弱项分析一次完成',
    excerpt:
      '教师配置题型与知识点后，系统结合题库与模型动态组卷；提交即评分，并按维度输出学习报告。',
    source: '智能组卷',
    time: '按章',
  },
  {
    kind: '共享',
    badge: '精选',
    title: '课程智能体：一门课一套，可共享、可采纳',
    excerpt:
      '知识库按课程与班级隔离运行；优质智能体可发布共享，其他教师一键采纳到本班，不必从零搭建。',
    source: '多课程隔离',
    time: '可复用',
  },
]

const teacherFeatures = [
  { text: '上传课件与教材，建立章节知识库', included: true },
  { text: '配置题库、考核规则与知识点', included: true },
  { text: '查看答卷报告并介入辅导', included: true },
  { text: '共享智能体，或采纳他人优质课程', included: true },
  { text: '管理班级学生与调用日志', included: true },
]

const studentFeatures = [
  { text: '按班级检索资料，随时发起课程问答', included: true },
  { text: '沿章节路线学习并完成考核', included: true },
  { text: '查看薄弱点报告，接收知识推送', included: true },
  { text: '进入课程群聊，与同学协作讨论', included: true },
  { text: '一份智能体贯穿问、学、测全过程', included: true },
]

const featureTags = ['课程问答', '章节路线', '群组讨论', '资料索引', '智能体共享', '知识推送']

onMounted(async () => {
  if (!auth.token) return
  if (auth.user) {
    router.replace('/home')
    return
  }
  const me = await auth.fetchMe()
  if (me) router.replace('/home')
})

function goLogin() {
  router.push('/login')
}

function goRegister() {
  router.push('/register')
}
</script>

<template>
  <div class="lp">
    <a href="#main" class="lp-skip">跳转到主要内容</a>

    <header class="lp-nav">
      <div class="lp-nav__inner">
        <button type="button" class="lp-nav__logo" @click="router.push('/welcome')">
          <span class="lp-nav__mark" aria-hidden="true">∞</span>
          <span>CodeInfinity</span>
        </button>
        <nav class="lp-nav__actions" aria-label="账户">
          <button type="button" class="btn btn--ghost" @click="goLogin">登录</button>
          <button type="button" class="btn btn--primary" @click="goRegister">免费开始</button>
        </nav>
      </div>
    </header>

    <main id="main">
      <!-- Hero：对齐 BestBlogs「发现真正适合你的…」结构 -->
      <section class="lp-hero">
        <div class="lp-hero__inner">
          <p class="lp-hero__eyebrow">AI 驱动的课程智能教学助手</p>
          <h1 class="lp-hero__title">发现真正适合你的智能教学闭环</h1>
          <p class="lp-hero__lead">
            CodeInfinity 把课程资料、RAG 答疑与章节考核放进同一套智能体——少切换工具，多把精力留在教与学本身。
          </p>
          <ul class="lp-hero__bullets">
            <li>答得更准一些</li>
            <li>教得更好一些</li>
            <li>学得更顺一些</li>
          </ul>
          <div class="lp-hero__cta">
            <button type="button" class="btn btn--primary btn--lg" @click="goLogin">体验课程问答</button>
            <button type="button" class="btn btn--outline btn--lg" @click="goRegister">浏览功能并注册</button>
          </div>
        </div>
      </section>

      <!-- Spotlight：对齐「最近一期」卡片 -->
      <section class="lp-spotlight" aria-labelledby="spotlight-title">
        <div class="lp-spotlight__inner">
          <div class="lp-spotlight__meta">
            <span class="lp-spotlight__label">教学主线</span>
            <span class="lp-spotlight__sep">·</span>
            <span class="lp-spotlight__date">课程智能体全流程</span>
          </div>
          <h2 id="spotlight-title" class="lp-spotlight__title">
            上传资料 → 检索答疑 → 章节路线 → 自动考核 → 弱项推送
          </h2>
          <div class="lp-spotlight__stats">
            <span>资料建库</span>
            <span>流式问答</span>
            <span>维度报告</span>
          </div>
          <p class="lp-spotlight__desc">
            教师一次上传课件，系统切片建索引；学生沿章学习、完成考核后立即看到薄弱点，再收到针对性巩固推送。同一套智能体，按班级隔离数据。
          </p>
          <button type="button" class="lp-spotlight__link" @click="goLogin">
            进入平台体验 →
          </button>
        </div>
      </section>

      <!-- Compare：对齐 Free / Pro -->
      <section class="lp-compare" aria-labelledby="compare-title">
        <div class="lp-compare__head">
          <h2 id="compare-title">角色不同，路径清晰</h2>
          <p>
            教师管内容与评价，学生走问学测路径。Free 对应「开箱即用的教学席位」，不必比价格——比的是各自最该专注的事。
          </p>
        </div>
        <div class="lp-compare__grid">
          <article class="lp-plan">
            <header class="lp-plan__head">
              <p class="lp-plan__label">教师席位</p>
              <p class="lp-plan__price">内容<span>主导</span></p>
              <p class="lp-plan__hint">上传、配置、共享、介入</p>
            </header>
            <ul class="lp-plan__list">
              <li v-for="item in teacherFeatures" :key="item.text">{{ item.text }}</li>
            </ul>
            <button type="button" class="btn btn--outline btn--block" @click="goLogin">教师登录</button>
          </article>
          <article class="lp-plan lp-plan--featured">
            <div class="lp-plan__ribbon">推荐路径</div>
            <header class="lp-plan__head">
              <p class="lp-plan__label">学生席位</p>
              <p class="lp-plan__price">学习<span>主线</span></p>
              <p class="lp-plan__hint">问答、讨论、考核、推送</p>
            </header>
            <ul class="lp-plan__list">
              <li v-for="item in studentFeatures" :key="item.text">{{ item.text }}</li>
            </ul>
            <button type="button" class="btn btn--primary btn--block" @click="goRegister">学生注册</button>
          </article>
        </div>
      </section>

      <!-- Steps：对齐「可信的私人阅读助手」 -->
      <section class="lp-steps" aria-labelledby="steps-title">
        <div class="lp-steps__head">
          <h2 id="steps-title">可信的课程智能体，从你上传的内容开始</h2>
          <p>先划定知识边界，再让 AI 放大效率——教什么、考什么、如何理解，始终由教师把关。</p>
        </div>
        <ol class="lp-steps__list">
          <li>
            <span class="lp-steps__num">01</span>
            <div>
              <h3>上传你信任的课程来源</h3>
              <p>课件、教材、试卷与视频字幕进入章节知识库。按课程智能体与班级隔离，学生只看得到该看的范围。</p>
            </div>
          </li>
          <li>
            <span class="lp-steps__num">02</span>
            <div>
              <h3>告诉系统这门课怎么教、怎么考</h3>
              <p>配置知识点、题库与考核规则。系统据此组卷、评分，并生成维度学习报告，而不是泛泛给个分数。</p>
            </div>
          </li>
          <li>
            <span class="lp-steps__num">03</span>
            <div>
              <h3>每天让问、学、测更贴近本班</h3>
              <p>学生沿章节路线前进，随时基于资料提问；考核后的弱项会进入知识推送，读得越多、练得越多，越贴合真实进度。</p>
            </div>
          </li>
        </ol>
        <blockquote class="lp-steps__quote">
          <span>AI 放大教学判断力，不替代教学判断力。</span>
          <span>教什么、信什么、如何评价，始终由你决定。</span>
        </blockquote>
      </section>

      <!-- Picks：对齐「今天值得读的」 -->
      <section class="lp-picks" aria-labelledby="picks-title">
        <div class="lp-picks__head">
          <h2 id="picks-title">今天值得用的，平台已经备好</h2>
          <p class="lp-picks__sub">
            从资料入库到弱项巩固，先由检索与规则分流，再由教师配置校准——把精力留给真正重要的教学决策。
          </p>
        </div>
        <div class="lp-picks__grid">
          <article v-for="item in highlights" :key="item.title" class="lp-pick">
            <div class="lp-pick__top">
              <span class="lp-pick__kind">{{ item.kind }}</span>
              <span class="lp-pick__badge">{{ item.badge }}</span>
            </div>
            <h3 class="lp-pick__title">{{ item.title }}</h3>
            <p class="lp-pick__excerpt">{{ item.excerpt }}</p>
            <p class="lp-pick__source">{{ item.source }} · {{ item.time }}</p>
          </article>
        </div>
      </section>

      <div class="lp-marquee" aria-hidden="true">
        <div class="lp-marquee__track">
          <span v-for="(tag, i) in [...featureTags, ...featureTags, ...featureTags, ...featureTags]" :key="i">
            {{ tag }}
          </span>
        </div>
      </div>

      <section class="lp-end">
        <h2>准备好开始了吗？</h2>
        <p>登录后选择课程智能体，问、学、测就在同一条路上。</p>
        <div class="lp-end__cta">
          <button type="button" class="btn btn--primary btn--lg" @click="goLogin">立即登录</button>
          <button type="button" class="btn btn--outline btn--lg" @click="goRegister">免费注册</button>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.lp {
  /* 浅色系，贴近智能体页 Element Plus 配色 */
  --bg: #f5f7fa;
  --surface: #ffffff;
  --surface-2: #eef2f6;
  --ink: #303133;
  --muted: #606266;
  --line: #e4e7ed;
  --primary: #409eff;
  --primary-fg: #ffffff;
  --primary-soft: rgba(64, 158, 255, 0.1);
  --accent: #e6a23c;
  --accent-soft: rgba(230, 162, 60, 0.12);
  --radius: 14px;
  --shadow: 0 1px 2px rgba(48, 49, 51, 0.04), 0 8px 24px rgba(48, 49, 51, 0.06);

  min-height: 100vh;
  background: var(--bg);
  color: var(--ink);
  font-family:
    'Noto Sans SC',
    'PingFang SC',
    'Hiragino Sans GB',
    'Microsoft YaHei',
    system-ui,
    -apple-system,
    sans-serif;
  color-scheme: light;
}

.lp-skip {
  position: absolute;
  left: -9999px;
}

.lp-skip:focus {
  left: 16px;
  top: 16px;
  z-index: 100;
  padding: 8px 12px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--ink);
}

.btn {
  border: none;
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  border-radius: 10px;
  padding: 9px 18px;
  transition:
    background 0.2s ease,
    color 0.2s ease,
    border-color 0.2s ease,
    box-shadow 0.2s ease;
}

.btn--ghost {
  background: transparent;
  color: var(--ink);
}

.btn--ghost:hover {
  background: rgba(64, 158, 255, 0.08);
}

.btn--outline {
  background: var(--surface);
  color: var(--ink);
  border: 1px solid var(--line);
}

.btn--outline:hover {
  border-color: #c0c4cc;
  background: var(--surface-2);
}

.btn--primary {
  background: var(--primary);
  color: var(--primary-fg);
  box-shadow: 0 1px 2px rgba(64, 158, 255, 0.25);
}

.btn--primary:hover {
  background: #66b1ff;
}

.btn--lg {
  padding: 13px 24px;
  font-size: 0.98rem;
}

.btn--block {
  width: 100%;
  margin-top: 24px;
}

.lp-nav {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(245, 247, 250, 0.88);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--line);
}

.lp-nav__inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 960px;
  margin: 0 auto;
  padding: 14px 24px;
}

.lp-nav__logo {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--ink);
  padding: 0;
  letter-spacing: -0.02em;
}

.lp-nav__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 0.95rem;
}

.lp-nav__actions {
  display: flex;
  gap: 8px;
}

.lp-hero {
  max-width: 960px;
  margin: 0 auto;
  padding: 72px 24px 48px;
  text-align: center;
  animation: fade-up 0.6s ease both;
}

.lp-hero__inner {
  max-width: 56rem;
  margin: 0 auto;
}

.lp-hero__eyebrow {
  margin: 0 0 18px;
  font-size: 0.92rem;
  font-weight: 500;
  color: var(--primary);
}

.lp-hero__title {
  margin: 0 0 20px;
  font-size: clamp(2rem, 5vw, 3.15rem);
  font-weight: 700;
  line-height: 1.18;
  letter-spacing: -0.03em;
  color: var(--ink);
  white-space: nowrap;
}

.lp-hero__lead {
  margin: 0 auto 22px;
  max-width: 36rem;
  font-size: 1.05rem;
  line-height: 1.75;
  color: var(--muted);
}

.lp-hero__bullets {
  margin: 0 auto 28px;
  padding: 0;
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px 28px;
}

.lp-hero__bullets li {
  position: relative;
  padding-left: 14px;
  font-size: 0.95rem;
  color: var(--ink);
}

.lp-hero__bullets li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.55em;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--accent);
}

.lp-hero__cta {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
}

.lp-spotlight {
  max-width: 960px;
  margin: 0 auto;
  padding: 0 24px 56px;
  animation: fade-up 0.65s ease 0.06s both;
}

.lp-spotlight__inner {
  padding: 28px 30px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: calc(var(--radius) + 2px);
  box-shadow: var(--shadow);
  text-align: left;
  transition:
    background 0.22s ease,
    border-color 0.22s ease,
    box-shadow 0.22s ease,
    transform 0.22s ease;
}

.lp-spotlight__inner:hover {
  background: #f8fbff;
  border-color: rgba(64, 158, 255, 0.28);
  box-shadow: 0 4px 16px rgba(64, 158, 255, 0.1);
  transform: translateY(-2px);
}

.lp-spotlight__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 0.82rem;
  color: var(--muted);
}

.lp-spotlight__label {
  color: var(--accent);
  font-weight: 600;
}

.lp-spotlight__sep {
  opacity: 0.5;
}

.lp-spotlight__title {
  margin: 0 0 12px;
  font-size: clamp(1.15rem, 2.4vw, 1.4rem);
  font-weight: 600;
  line-height: 1.45;
  letter-spacing: -0.015em;
}

.lp-spotlight__stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.lp-spotlight__stats span {
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 0.75rem;
  font-weight: 500;
}

.lp-spotlight__desc {
  margin: 0 0 18px;
  font-size: 0.94rem;
  line-height: 1.75;
  color: var(--muted);
}

.lp-spotlight__link {
  display: inline-flex;
  border: none;
  background: none;
  padding: 0;
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  color: var(--primary);
}

.lp-spotlight__link:hover {
  text-decoration: underline;
}

.lp-compare {
  max-width: 960px;
  margin: 0 auto;
  padding: 16px 24px 64px;
}

.lp-compare__head {
  margin-bottom: 28px;
  text-align: center;
}

.lp-compare__head h2 {
  margin: 0 0 10px;
  font-size: clamp(1.35rem, 3vw, 1.75rem);
  font-weight: 700;
  letter-spacing: -0.02em;
}

.lp-compare__head p {
  margin: 0 auto;
  max-width: 34rem;
  color: var(--muted);
  line-height: 1.7;
  font-size: 0.95rem;
}

.lp-compare__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}

.lp-plan {
  position: relative;
  padding: 28px 26px 30px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  transition:
    background 0.22s ease,
    border-color 0.22s ease,
    box-shadow 0.22s ease,
    transform 0.22s ease;
}

.lp-plan:hover {
  background: #f8fbff;
  border-color: rgba(64, 158, 255, 0.28);
  box-shadow: 0 4px 16px rgba(64, 158, 255, 0.08);
  transform: translateY(-2px);
}

.lp-plan--featured {
  border-color: rgba(64, 158, 255, 0.35);
  box-shadow: var(--shadow);
}

.lp-plan--featured:hover {
  background: #f0f7ff;
  border-color: rgba(64, 158, 255, 0.45);
  box-shadow: 0 6px 20px rgba(64, 158, 255, 0.12);
}

.lp-plan__ribbon {
  position: absolute;
  top: 14px;
  right: 14px;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 0.72rem;
  font-weight: 600;
}

.lp-plan__head {
  margin-bottom: 20px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--line);
}

.lp-plan__label {
  margin: 0 0 8px;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--muted);
}

.lp-plan__price {
  margin: 0 0 6px;
  font-size: 1.65rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.2;
}

.lp-plan__price span {
  margin-left: 6px;
  font-size: 0.95rem;
  font-weight: 500;
  color: var(--muted);
}

.lp-plan__hint {
  margin: 0;
  font-size: 0.82rem;
  color: #909399;
}

.lp-plan__list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.lp-plan__list li {
  position: relative;
  padding-left: 22px;
  font-size: 0.9rem;
  line-height: 1.55;
  color: var(--ink);
}

.lp-plan__list li::before {
  content: '✓';
  position: absolute;
  left: 0;
  color: var(--primary);
  font-weight: 700;
  font-size: 0.85rem;
}

.lp-steps {
  max-width: 960px;
  margin: 0 auto;
  padding: 48px 24px 64px;
}

.lp-steps__head {
  margin: 0 auto 40px;
  max-width: none;
  text-align: center;
}

.lp-steps__head h2 {
  margin: 0 0 12px;
  font-size: clamp(1.35rem, 3vw, 1.75rem);
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.3;
}

.lp-steps__head p {
  margin: 0;
  color: var(--muted);
  line-height: 1.7;
  white-space: nowrap;
}

.lp-steps__list {
  margin: 0 0 28px;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 28px;
  max-width: 40rem;
  margin-left: auto;
  margin-right: auto;
}

.lp-steps__list li {
  display: grid;
  grid-template-columns: 3.2rem 1fr;
  gap: 14px;
  align-items: start;
}

.lp-steps__num {
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--primary);
  line-height: 1.4;
  letter-spacing: -0.02em;
}

.lp-steps__list h3 {
  margin: 0 0 8px;
  font-size: 1.05rem;
  font-weight: 600;
}

.lp-steps__list p {
  margin: 0;
  font-size: 0.94rem;
  line-height: 1.7;
  color: var(--muted);
}

.lp-steps__quote {
  margin: 0 auto 32px;
  max-width: 40rem;
  padding: 0 0 0 20px;
  border: none;
  border-left: 3px solid var(--primary);
  background: transparent;
  font-size: 0.98rem;
  line-height: 1.85;
  color: var(--muted);
  text-align: left;
}

.lp-steps__quote span {
  display: block;
}

.lp-picks {
  max-width: 960px;
  margin: 0 auto;
  padding: 24px 24px 0;
}

.lp-picks__head {
  margin: 0 auto 28px;
  max-width: 36rem;
  text-align: center;
}

.lp-picks__head h2 {
  margin: 0 0 12px;
  font-size: clamp(1.35rem, 3vw, 1.75rem);
  font-weight: 700;
  letter-spacing: -0.02em;
}

.lp-picks__sub {
  margin: 0;
  color: var(--muted);
  line-height: 1.7;
  font-size: 0.94rem;
}

.lp-picks__grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.lp-pick {
  padding: 20px 20px 22px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  transition:
    background 0.22s ease,
    border-color 0.22s ease,
    box-shadow 0.22s ease,
    transform 0.22s ease;
}

.lp-pick:hover {
  background: #f8fbff;
  border-color: rgba(64, 158, 255, 0.28);
  box-shadow: 0 4px 16px rgba(64, 158, 255, 0.08);
  transform: translateY(-2px);
}

.lp-pick__top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.lp-pick__kind {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--muted);
}

.lp-pick__badge {
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 0.7rem;
  font-weight: 600;
}

.lp-pick__title {
  margin: 0 0 10px;
  font-size: 0.96rem;
  font-weight: 600;
  line-height: 1.45;
}

.lp-pick__excerpt {
  margin: 0 0 14px;
  font-size: 0.86rem;
  line-height: 1.65;
  color: var(--muted);
}

.lp-pick__source {
  margin: 0;
  font-size: 0.75rem;
  color: #909399;
}

.lp-marquee {
  position: relative;
  left: 50%;
  width: 100vw;
  margin: 48px 0 48px -50vw;
  overflow: hidden;
  padding: 14px 0;
  background: var(--surface-2);
}

.lp-marquee__track {
  display: flex;
  gap: 48px;
  width: max-content;
  animation: marquee 40s linear infinite;
  will-change: transform;
}

.lp-marquee__track span {
  flex-shrink: 0;
  padding: 6px 14px;
  border-radius: 999px;
  background: var(--surface);
  border: 1px solid var(--line);
  font-size: 0.8rem;
  font-weight: 500;
  letter-spacing: 0.04em;
  color: var(--muted);
  white-space: nowrap;
}

@keyframes marquee {
  from {
    transform: translateX(0);
  }
  to {
    transform: translateX(-25%);
  }
}

.lp-end {
  max-width: 960px;
  margin: 0 auto;
  padding: 0 24px 56px;
  text-align: center;
}

.lp-end h2 {
  margin: 0 0 10px;
  font-size: 1.4rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.lp-end p {
  margin: 0 0 22px;
  color: var(--muted);
}

.lp-end__cta {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
}

@keyframes fade-up {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 900px) {
  .lp-picks__grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .lp-hero {
    padding-top: 48px;
    text-align: left;
  }

  .lp-hero__inner {
    margin: 0;
  }

  .lp-hero__lead {
    margin-left: 0;
    margin-right: 0;
  }

  .lp-hero__bullets {
    justify-content: flex-start;
    flex-direction: column;
    gap: 8px;
  }

  .lp-hero__cta {
    justify-content: flex-start;
  }

  .lp-compare__grid {
    grid-template-columns: 1fr;
  }

  .lp-compare__head,
  .lp-steps__head,
  .lp-picks__head {
    text-align: left;
  }

  .lp-steps__list li {
    grid-template-columns: 2.4rem 1fr;
  }

  .lp-steps__head p {
    white-space: normal;
  }
}
</style>
