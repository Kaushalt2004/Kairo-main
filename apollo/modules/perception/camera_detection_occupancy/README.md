# Apollo BEV+OCC 检测模块

## 系统要求

### 推荐环境
- **建议使用 Apollo 11.0 包管理模式**

**重要提示**：为获得最佳性能和兼容性，建议用户通过 Apollo 11.0 的包管理系统安装和使用 BEV+OCC 功能，而不是自行编译源码。

## 文档与支持

### 关键链接
- [Apollo 11.0 包管理安装教程](https://apollo.baidu.com/community/Apollo-Homepage-Document?doc=BYFxAcGcC4HpYIbgPYBtXIHQCMEEsATAV0wGNkBbWA5UyRFdZWVBEAU0hFgoIH0adPgCY%2BADwCiAVnEBBCeIAcATnETFcgMxKZkgGxKAwkoDsa3YoAi45WdGSLxsYt0SzY%2BXICMa98oAMSgYALF7%2B2NhemsLBJsrCYZqKwors7AikBIp6miYmpFJSXpigFKhAA)
- [Apollo 11.0视觉检测与占据栅格模型介绍及教程](https://apollo.baidu.com/community/Apollo-Homepage-Document?doc=BYFxAcGcC4HpYIbgPYBtXIHQCMEEsATAV0wGNkBbWA5UyRFdZWVBEAU0hFgoIH0adPgCY%2BADwCiAVnEAhAILiAnABZxEgOzK1Y%2BQA51M3ROUnJBsbK2WZoyUdkBhcXoAMhlwDFlARnUXZdzE9AGY%2BKVIEADM9KRD2AgA2KJCpPQI9RKVhPR9sFWFhEMSsjQ0fTFAKVCA)

### 模型文件
- **BEV+OCC 模型下载**：[apollo_bevnet.onnx](https://apollo-perception.bj.bcebos.com/v1/park_model/apollo_bevnet.onnx?authorization=bce-auth-v1%2F58ab9c524850484da494659d339218ee%2F2026-02-27T10%3A03%3A44Z%2F-1%2Fhost%2F472626abb13a136f1f96e04442123fddac9d1464e07360feeb933779be866dae)

**模型存放路径**：请将下载的 `apollo_bevnet.onnx` 文件放置在 `modules/perception/data/models/apollo_bevnet_onnx` 目录中。

---

# Apollo BEV+OCC Detection Module

## System Requirements

### Recommended Environment
- **Recommended to use Apollo 11.0 Package Management**

**Important Note**: For optimal performance and compatibility, it is recommended to install and use BEV+OCC functionality through Apollo 11.0's package management system rather than compiling from source.

## Documentation & Support

### Key Links
- [Apollo 11.0 Package Management Installation Tutorial](https://apollo.baidu.com/community/Apollo-Homepage-Document?doc=BYFxAcGcC4HpYIbgPYBtXIHQCMEEsATAV0wGNkBbWA5UyRFdZWVBEAU0hFgoIH0adPgCY%2BADwCiAVnEBBCeIAcATnETFcgMxKZkgGxKAwkoDsa3YoAi45WdGSLxsYt0SzY%2BXICMa98oAMSgYALF7%2B2NhemsLBJsrCYZqKwors7AikBIp6miYmpFJSXpigFKhAA)
- [Apollo 11.0 Visual Detection and Occupancy Grid Model Introduction & Tutorial](https://apollo.baidu.com/community/Apollo-Homepage-Document?doc=BYFxAcGcC4HpYIbgPYBtXIHQCMEEsATAV0wGNkBbWA5UyRFdZWVBEAU0hFgoIH0adPgCY%2BADwCiAVnEAhAILiAnABZxEgOzK1Y%2BQA51M3ROUnJBsbK2WZoyUdkBhcXoAMhlwDFlARnUXZdzE9AGY%2BKVIEADM9KRD2AgA2KJCpPQI9RKVhPR9sFWFhEMSsjQ0fTFAKVCA)

### Model Files
- **BEV+OCC Model Download**: [apollo_bevnet.onnx](https://apollo-perception.bj.bcebos.com/v1/park_model/apollo_bevnet.onnx?authorization=bce-auth-v1%2F58ab9c524850484da494659d339218ee%2F2026-02-27T10%3A03%3A44Z%2F-1%2Fhost%2F472626abb13a136f1f96e04442123fddac9d1464e07360feeb933779be866dae)

**Model Storage Path**: Please place the downloaded `apollo_bevnet.onnx` file in the `modules/perception/data/models/apollo_bevnet_onnx` directory.