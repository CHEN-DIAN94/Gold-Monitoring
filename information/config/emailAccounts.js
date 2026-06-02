module.exports = [
  {
    id: '1',
    name: 'QQ邮箱',
    email: process.env.QQ_EMAIL || '1359370450@qq.com',
    password: process.env.QQ_EMAIL_PASSWORD,  // 修复：从环境变量读取密码，不再硬编码
    imapHost: 'imap.qq.com',
    imapPort: 993,
    imapTls: true,
    description: 'QQ邮箱账户'
  },
  {
    id: '2',
    name: 'Outlook邮箱',
    email: process.env.OUTLOOK_EMAIL || 'zhx2486369@outlook.com',
    password: process.env.OUTLOOK_EMAIL_PASSWORD,  // 修复：从环境变量读取密码
    imapHost: 'outlook.office365.com',
    imapPort: 993,
    imapTls: true,
    description: 'Outlook邮箱账户'
  }
];