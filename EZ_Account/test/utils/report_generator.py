"""
测试报告生成器

生成详细的HTML和文本格式测试报告
"""

import json
import time
from typing import Dict, Any, List, Optional
from datetime import datetime


class ReportGenerator:
    """测试报告生成器"""

    def __init__(self):
        self.report_data = {}

    def generate_html_report(self, results: Dict[str, Any], output_file: str = "test_report.html"):
        """生成HTML格式的测试报告"""
        html_template = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EZChain Account测试报告</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #e0e0e0;
        }
        .header h1 {
            color: #2c3e50;
            margin: 0;
            font-size: 2.5em;
        }
        .header p {
            color: #7f8c8d;
            margin: 10px 0 0 0;
            font-size: 1.1em;
        }
        .summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .summary-card {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            border-left: 4px solid #3498db;
        }
        .summary-card h3 {
            margin: 0 0 10px 0;
            color: #2c3e50;
            font-size: 1.2em;
        }
        .summary-card .value {
            font-size: 2em;
            font-weight: bold;
            color: #3498db;
        }
        .test-section {
            margin-bottom: 30px;
            padding: 20px;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
        }
        .test-section h2 {
            margin-top: 0;
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 10px;
        }
        .status-success {
            color: #27ae60;
            font-weight: bold;
        }
        .status-error {
            color: #e74c3c;
            font-weight: bold;
        }
        .status-warning {
            color: #f39c12;
            font-weight: bold;
        }
        .metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin: 15px 0;
        }
        .metric {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 6px;
            text-align: center;
        }
        .metric-label {
            font-size: 0.9em;
            color: #7f8c8d;
            margin-bottom: 5px;
        }
        .metric-value {
            font-size: 1.3em;
            font-weight: bold;
            color: #2c3e50;
        }
        .error-list {
            background: #fdf2f2;
            border: 1px solid #f5c6cb;
            border-radius: 6px;
            padding: 15px;
            margin-top: 15px;
        }
        .error-item {
            color: #721c24;
            margin-bottom: 5px;
            padding-left: 20px;
            position: relative;
        }
        .error-item:before {
            content: "•";
            position: absolute;
            left: 0;
        }
        .timestamp {
            color: #95a5a6;
            font-size: 0.9em;
            text-align: center;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #e0e0e0;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔬 EZChain Account测试报告</h1>
            <p>生成时间: {timestamp}</p>
        </div>

        <div class="summary">
            <div class="summary-card">
                <h3>总体结果</h3>
                <div class="value {overall_status_class}">{overall_status}</div>
            </div>
            <div class="summary-card">
                <h3>执行时间</h3>
                <div class="value">{execution_time:.2f}s</div>
            </div>
            <div class="summary-card">
                <h3>测试套件</h3>
                <div class="value">{test_suites}</div>
            </div>
            <div class="summary-card">
                <h3>总错误数</h3>
                <div class="value {error_status_class}">{total_errors}</div>
            </div>
        </div>

        {test_sections}

        <div class="timestamp">
            报告生成时间: {timestamp}<br>
            EZChain Account测试系统 v1.0
        </div>
    </div>
</body>
</html>
        """

        # 准备数据
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        execution_time = results.get('execution_time', 0)
        total_errors = results.get('total_errors', 0)
        overall_success = results.get('overall_success', False)
        overall_status = "✅ 成功" if overall_success else "❌ 失败"
        overall_status_class = "status-success" if overall_success else "status-error"
        error_status_class = "status-success" if total_errors == 0 else "status-error"

        # 统计测试套件
        test_suites = []
        if results.get('quick_test'):
            test_suites.append("快速测试")
        if results.get('standard_test'):
            test_suites.append("标准测试")
        if results.get('debug_test'):
            test_suites.append("调试测试")
        test_suites_count = len(test_suites)

        # 生成测试部分
        test_sections = ""

        test_names = {
            'quick_test': '快速测试',
            'standard_test': '标准集成测试',
            'debug_test': '调试测试'
        }

        for test_key, test_name in test_names.items():
            if test_key in results and results[test_key]:
                result = results[test_key]
                test_sections += self._generate_test_section(test_name, result)

        # 生成HTML
        html_content = html_template.format(
            timestamp=timestamp,
            overall_status=overall_status,
            overall_status_class=overall_status_class,
            execution_time=execution_time,
            test_suites=test_suites_count,
            total_errors=total_errors,
            error_status_class=error_status_class,
            test_sections=test_sections
        )

        # 写入文件
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

        return output_file

    def _generate_test_section(self, test_name: str, result: Dict[str, Any]) -> str:
        """生成单个测试部分"""
        if test_name == "调试测试":
            status = "✅ 通过" if result.get('debug_test_passed', False) else "❌ 失败"
            status_class = "status-success" if result.get('debug_test_passed', False) else "status-error"

            return f"""
        <div class="test-section">
            <h2>🧪 {test_name}</h2>
            <div class="metrics">
                <div class="metric">
                    <div class="metric-label">测试结果</div>
                    <div class="metric-value {status_class}">{status}</div>
                </div>
            </div>
        </div>
            """
        else:
            accounts_created = result.get('accounts_created', 0)
            transactions_created = result.get('transactions_created', 0)
            success_rate = result.get('success_rate', 0)
            errors = result.get('errors', [])

            status = "✅ 成功" if success_rate >= 80 else "❌ 失败"
            status_class = "status-success" if success_rate >= 80 else "status-error"

            error_section = ""
            if errors:
                error_items = "".join([f'<div class="error-item">{error}</div>' for error in errors])
                error_section = f"""
                <div class="error-list">
                    <h4>错误列表:</h4>
                    {error_items}
                </div>
                """

            return f"""
        <div class="test-section">
            <h2>🧪 {test_name}</h2>
            <div class="metrics">
                <div class="metric">
                    <div class="metric-label">创建账户</div>
                    <div class="metric-value">{accounts_created}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">创建交易</div>
                    <div class="metric-value">{transactions_created}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">成功率</div>
                    <div class="metric-value {status_class}">{success_rate:.1f}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">错误数</div>
                    <div class="metric-value">{len(errors)}</div>
                </div>
            </div>
            {error_section}
        </div>
            """

    def generate_json_report(self, results: Dict[str, Any], output_file: str = "test_report.json"):
        """生成JSON格式的测试报告"""
        # 添加时间戳
        results['report_timestamp'] = datetime.now().isoformat()
        results['report_version'] = "1.0"

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        return output_file

    def generate_text_report(self, results: Dict[str, Any], output_file: str = "test_report.txt"):
        """生成文本格式的测试报告"""
        lines = []

        # 标题
        lines.append("=" * 60)
        lines.append("EZChain Account测试报告")
        lines.append("=" * 60)
        lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"报告版本: 1.0")
        lines.append("")

        # 总体结果
        lines.append("📊 总体结果")
        lines.append("-" * 30)
        overall_success = results.get('overall_success', False)
        lines.append(f"总体结果: {'✅ 成功' if overall_success else '❌ 失败'}")
        lines.append(f"执行时间: {results.get('execution_time', 0):.2f} 秒")
        lines.append(f"总错误数: {results.get('total_errors', 0)}")
        lines.append("")

        # 测试详情
        test_names = {
            'quick_test': '快速测试',
            'standard_test': '标准集成测试',
            'debug_test': '调试测试'
        }

        for test_key, test_name in test_names.items():
            if test_key in results and results[test_key]:
                result = results[test_key]
                lines.append(f"🧪 {test_name}")
                lines.append("-" * 30)

                if test_name == "调试测试":
                    status = "✅ 通过" if result.get('debug_test_passed', False) else "❌ 失败"
                    lines.append(f"测试结果: {status}")
                else:
                    accounts_created = result.get('accounts_created', 0)
                    transactions_created = result.get('transactions_created', 0)
                    success_rate = result.get('success_rate', 0)
                    errors = result.get('errors', [])

                    lines.append(f"创建账户: {accounts_created}")
                    lines.append(f"创建交易: {transactions_created}")
                    lines.append(f"成功率: {success_rate:.1f}%")
                    lines.append(f"错误数: {len(errors)}")

                    if errors:
                        lines.append("错误列表:")
                        for i, error in enumerate(errors, 1):
                            lines.append(f"  {i}. {error}")

                lines.append("")

        # 页脚
        lines.append("=" * 60)
        lines.append("EZChain Account测试系统 v1.0")
        lines.append("=" * 60)

        # 写入文件
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        return output_file


def generate_all_reports(results: Dict[str, Any], base_name: str = "ezchain_test_report"):
    """生成所有格式的报告"""
    generator = ReportGenerator()

    reports = {
        'html': generator.generate_html_report(results, f"{base_name}.html"),
        'json': generator.generate_json_report(results, f"{base_name}.json"),
        'text': generator.generate_text_report(results, f"{base_name}.txt")
    }

    return reports