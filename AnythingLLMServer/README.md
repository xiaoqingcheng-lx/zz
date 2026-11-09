# AnythingLLMServer：本地私有知识库 + 文档上传网页

本目录是 [AnythingLLM](https://anythingllm.com/) 桌面版（`anthingllmserver/`，
体积大，不进仓库，用官方安装包自行安装即可）+ 一个自研的 **文档上传网页**。

## anythingllm-upload：一键上传并嵌入

`index.html` 是一个零依赖的纯静态页面，解决 AnythingLLM 自带 UI 上传文档
步骤繁琐的问题：打开页面 → 选文件 → 自动上传、自动触发向量化嵌入，
并且用 **向量检索反向验证** 文档真的能被搜到（显示相似度百分比）。

### 使用方法

1. 启动 AnythingLLM 桌面版（默认监听 `localhost:3001`）；
2. 在「开发者设置 → API Keys」里生成一个 API Key；
3. 把 Key 存到本目录的 `apikey.local.txt`（纯文本，一个 Key 一行），
   **该文件含密钥，已被 .gitignore 排除，不会进仓库**；
   没有 txt 文件时页面会弹输入框，Key 记在浏览器 localStorage；
4. 双击打开 `index.html`（或任意静态服务器托管），选择文件上传。

### 页面验证逻辑

上传成功后，页面会用「文件名去扩展名」作为查询词调用
`/api/v1/workspace/<slug>/vector-search`，命中即显示
`上传成功，嵌入已生效（检索命中，相似度 xx%）`；
未命中则提示可能仍在后台嵌入排队。
