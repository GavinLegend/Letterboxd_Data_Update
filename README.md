# Share Site

这个目录已经是一个可以直接部署的静态网站。

## 目录说明

- `index.html`
  你真正要公开分享的网页入口
- `custom-report-data.json`
  页面里用到的分析数据
- `.nojekyll`
  让 GitHub Pages 按纯静态站点处理
- `publish_to_github.sh`
  把当前目录推到 GitHub 仓库的快捷脚本

## GitHub Pages 最短路径

### 方式一：网页手动上传

1. 在 GitHub 创建一个新的公开仓库。
2. 把这个目录里的所有文件上传到仓库根目录。
3. 打开仓库的 `Settings -> Pages`。
4. 在 `Build and deployment` 里选择 `Deploy from a branch`。
5. 选择 `main` 分支和 `/(root)`，保存。

### 方式二：本地脚本推送

先在 GitHub 网站上创建一个新的空公开仓库，然后在这个目录里运行：

```bash
chmod +x ./publish_to_github.sh
./publish_to_github.sh https://github.com/<你的用户名>/<你的仓库名>.git
```

推送完成后，再去 GitHub 仓库的：

`Settings -> Pages -> Deploy from a branch -> main -> /(root)`

保存后 GitHub 会给你一个公开 URL。

## 本地预览

在这个目录里运行：

```bash
python3 -m http.server 8000
```

然后打开：

`http://localhost:8000`
