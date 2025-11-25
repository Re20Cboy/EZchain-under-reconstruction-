#!/usr/bin/env python3
"""
EZChain多账户集成测试结果分析器

这个模块用于分析多账户集成测试的结果，
生成详细的测试报告和性能指标。

作者：Claude
日期：2025年1月
"""

import os
import json
import sys
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import matplotlib.pyplot as plt
import pandas as pd

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class TestMetrics:
    """测试性能指标"""
    transaction_throughput: float = 0.0  # 交易吞吐量 (TPS)
    block_generation_rate: float = 0.0   # 区块生成率 (BPS)
    average_block_time: float = 0.0      # 平均区块时间
    transaction_success_rate: float = 0.0 # 交易成功率
    vpb_update_efficiency: float = 0.0   # VPB更新效率
    system_stability_score: float = 0.0   # 系统稳定性评分


@dataclass
class TestReport:
    """测试报告"""
    test_name: str
    start_time: datetime
    end_time: datetime
    total_duration: float
    config: Dict[str, Any]
    metrics: TestMetrics
    raw_stats: Dict[str, Any]
    analysis: Dict[str, str]
    recommendations: List[str]


class TestAnalyzer:
    """测试结果分析器"""

    def __init__(self):
        self.reports: List[TestReport] = []

    def analyze_test_results(self, config, stats) -> TestReport:
        """分析测试结果"""

        # 计算性能指标
        metrics = self._calculate_metrics(config, stats)

        # 生成分析结果
        analysis = self._generate_analysis(config, stats, metrics)

        # 生成建议
        recommendations = self._generate_recommendations(config, stats, metrics)

        # 创建报告
        report = TestReport(
            test_name=f"MultiAccountTest_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            start_time=datetime.fromtimestamp(stats.start_time),
            end_time=datetime.fromtimestamp(stats.end_time),
            total_duration=stats.end_time - stats.start_time,
            config=asdict(config),
            metrics=metrics,
            raw_stats=asdict(stats),
            analysis=analysis,
            recommendations=recommendations
        )

        self.reports.append(report)
        return report

    def _calculate_metrics(self, config, stats) -> TestMetrics:
        """计算性能指标"""
        duration = stats.end_time - stats.start_time

        # 交易吞吐量 (每秒交易数)
        transaction_throughput = stats.total_transactions_created / duration if duration > 0 else 0

        # 区块生成率 (每秒区块数)
        block_generation_rate = stats.total_blocks_created / duration if duration > 0 else 0

        # 平均区块时间
        average_block_time = duration / stats.total_blocks_created if stats.total_blocks_created > 0 else 0

        # 交易成功率
        transaction_success_rate = stats.success_rate

        # VPB更新效率 (每秒更新数)
        vpb_update_efficiency = stats.total_vpb_updates / duration if duration > 0 else 0

        # 系统稳定性评分 (基于错误率和成功率)
        error_rate = len(stats.errors) / max(stats.total_transactions_created, 1)
        stability_score = max(0, 100 - error_rate * 100) * (transaction_success_rate / 100)

        return TestMetrics(
            transaction_throughput=transaction_throughput,
            block_generation_rate=block_generation_rate,
            average_block_time=average_block_time,
            transaction_success_rate=transaction_success_rate,
            vpb_update_efficiency=vpb_update_efficiency,
            system_stability_score=stability_score
        )

    def _generate_analysis(self, config, stats, metrics) -> Dict[str, str]:
        """生成分析结果"""
        analysis = {}

        # 性能分析
        if metrics.transaction_throughput > 10:
            analysis['performance'] = "优秀：系统表现出高交易吞吐量"
        elif metrics.transaction_throughput > 5:
            analysis['performance'] = "良好：系统表现出中等交易吞吐量"
        else:
            analysis['performance'] = "需要改进：系统交易吞吐量较低"

        # 稳定性分析
        if metrics.system_stability_score > 90:
            analysis['stability'] = "优秀：系统表现出高稳定性"
        elif metrics.system_stability_score > 70:
            analysis['stability'] = "良好：系统表现稳定"
        else:
            analysis['stability'] = "需要改进：系统稳定性较低"

        # 效率分析
        if metrics.transaction_success_rate > 95:
            analysis['efficiency'] = "优秀：交易成功率高"
        elif metrics.transaction_success_rate > 80:
            analysis['efficiency'] = "良好：交易成功率中等"
        else:
            analysis['efficiency'] = "需要改进：交易成功率较低"

        # VPB管理分析
        if metrics.vpb_update_efficiency > 5:
            analysis['vpb_management'] = "优秀：VPB更新效率高"
        elif metrics.vpb_update_efficiency > 2:
            analysis['vpb_management'] = "良好：VPB更新效率中等"
        else:
            analysis['vpb_management'] = "需要改进：VPB更新效率较低"

        return analysis

    def _generate_recommendations(self, config, stats, metrics) -> List[str]:
        """生成改进建议"""
        recommendations = []

        # 性能相关建议
        if metrics.transaction_throughput < 5:
            recommendations.append("考虑增加区块大小以提高交易吞吐量")
            recommendations.append("优化交易验证逻辑以减少处理时间")

        # 稳定性相关建议
        if len(stats.errors) > 0:
            recommendations.append("加强错误处理和恢复机制")
            recommendations.append("增加详细的日志记录以便问题诊断")

        # VPB管理相关建议
        if metrics.vpb_update_efficiency < 2:
            recommendations.append("优化VPB更新逻辑以提高效率")
            recommendations.append("考虑批量处理VPB更新操作")

        # 配置相关建议
        if metrics.average_block_time > config.block_interval * 1.5:
            recommendations.append("考虑调整区块间隔以匹配实际生成时间")

        # 成功率相关建议
        if metrics.transaction_success_rate < 90:
            recommendations.append("检查交易池容量和处理逻辑")
            recommendations.append("优化网络通信以减少交易丢失")

        # 资源使用建议
        if config.num_accounts > 5 and metrics.system_stability_score < 80:
            recommendations.append("考虑限制并发账户数量以提高稳定性")
            recommendations.append("优化资源分配和管理")

        return recommendations

    def generate_report_text(self, report: TestReport) -> str:
        """生成文本格式的测试报告"""
        lines = []

        lines.append("=" * 80)
        lines.append(f"📊 EZChain多账户集成测试报告")
        lines.append("=" * 80)
        lines.append("")

        # 基本信息
        lines.append("📋 基本信息")
        lines.append("-" * 40)
        lines.append(f"测试名称: {report.test_name}")
        lines.append(f"开始时间: {report.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"结束时间: {report.end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"总时长: {report.total_duration:.2f} 秒")
        lines.append("")

        # 配置信息
        lines.append("⚙️ 测试配置")
        lines.append("-" * 40)
        for key, value in report.config.items():
            lines.append(f"{key}: {value}")
        lines.append("")

        # 测试结果
        lines.append("📈 测试结果")
        lines.append("-" * 40)
        for key, value in report.raw_stats.items():
            if key != 'errors':
                lines.append(f"{key}: {value}")

        if report.raw_stats['errors']:
            lines.append("")
            lines.append("❌ 错误列表:")
            for i, error in enumerate(report.raw_stats['errors'], 1):
                lines.append(f"  {i}. {error}")
        lines.append("")

        # 性能指标
        lines.append("🚀 性能指标")
        lines.append("-" * 40)
        lines.append(f"交易吞吐量: {report.metrics.transaction_throughput:.2f} TPS")
        lines.append(f"区块生成率: {report.metrics.block_generation_rate:.2f} BPS")
        lines.append(f"平均区块时间: {report.metrics.average_block_time:.2f} 秒")
        lines.append(f"交易成功率: {report.metrics.transaction_success_rate:.2f}%")
        lines.append(f"VPB更新效率: {report.metrics.vpb_update_efficiency:.2f} UPS")
        lines.append(f"系统稳定性评分: {report.metrics.system_stability_score:.2f}/100")
        lines.append("")

        # 分析结果
        lines.append("🔍 分析结果")
        lines.append("-" * 40)
        for aspect, result in report.analysis.items():
            lines.append(f"{aspect}: {result}")
        lines.append("")

        # 改进建议
        lines.append("💡 改进建议")
        lines.append("-" * 40)
        if report.recommendations:
            for i, recommendation in enumerate(report.recommendations, 1):
                lines.append(f"{i}. {recommendation}")
        else:
            lines.append("系统表现良好，暂无改进建议")
        lines.append("")

        # 总体评价
        lines.append("📝 总体评价")
        lines.append("-" * 40)
        if report.metrics.system_stability_score > 90 and report.metrics.transaction_success_rate > 95:
            lines.append("✅ 测试结果优秀：系统表现出色，满足所有要求")
        elif report.metrics.system_stability_score > 70 and report.metrics.transaction_success_rate > 80:
            lines.append("✅ 测试结果良好：系统表现符合预期")
        else:
            lines.append("⚠️ 测试结果需要改进：系统存在一些问题需要解决")

        lines.append("")
        lines.append("=" * 80)

        return "\n".join(lines)

    def generate_report_json(self, report: TestReport) -> str:
        """生成JSON格式的测试报告"""
        # 转换datetime对象为字符串
        report_data = asdict(report)
        report_data['start_time'] = report.start_time.isoformat()
        report_data['end_time'] = report.end_time.isoformat()

        return json.dumps(report_data, indent=2, ensure_ascii=False)

    def save_report(self, report: TestReport, output_dir: str = "test_reports"):
        """保存测试报告到文件"""
        os.makedirs(output_dir, exist_ok=True)

        # 保存文本报告
        text_report = self.generate_report_text(report)
        text_file = os.path.join(output_dir, f"{report.test_name}.txt")
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write(text_report)

        # 保存JSON报告
        json_report = self.generate_report_json(report)
        json_file = os.path.join(output_dir, f"{report.test_name}.json")
        with open(json_file, 'w', encoding='utf-8') as f:
            f.write(json_report)

        print(f"📄 测试报告已保存:")
        print(f"   文本报告: {text_file}")
        print(f"   JSON报告: {json_file}")

    def compare_reports(self, report1: TestReport, report2: TestReport) -> Dict[str, Any]:
        """比较两个测试报告"""
        comparison = {
            'report1_name': report1.test_name,
            'report2_name': report2.test_name,
            'metrics_comparison': {},
            'improvement_areas': [],
            'regression_areas': []
        }

        # 比较各项指标
        metrics_fields = [
            'transaction_throughput', 'block_generation_rate', 'average_block_time',
            'transaction_success_rate', 'vpb_update_efficiency', 'system_stability_score'
        ]

        for field in metrics_fields:
            value1 = getattr(report1.metrics, field)
            value2 = getattr(report2.metrics, field)

            improvement = ((value2 - value1) / value1 * 100) if value1 != 0 else 0

            comparison['metrics_comparison'][field] = {
                'report1_value': value1,
                'report2_value': value2,
                'improvement_percent': improvement
            }

            if improvement > 10:
                comparison['improvement_areas'].append(f"{field}: +{improvement:.1f}%")
            elif improvement < -10:
                comparison['regression_areas'].append(f"{field}: {improvement:.1f}%")

        return comparison


def demo_analyzer():
    """演示测试分析器的使用"""
    print("🔬 EZChain测试结果分析器演示")
    print("=" * 50)

    # 创建示例配置和统计数据
    from multi_account_integration_test import TestConfig, TestStats
    import time

    # 示例配置
    config = TestConfig(
        num_accounts=3,
        num_transaction_rounds=10,
        transactions_per_round=3,
        block_interval=2.0,
        transaction_interval=0.5,
        test_duration=30,
        base_balance=5000,
        transaction_amount_range=(50, 200)
    )

    # 示例统计数据
    stats = TestStats(
        total_transactions_created=30,
        total_transactions_confirmed=28,
        total_blocks_created=10,
        total_vpb_updates=25,
        errors=["轻微的网络延迟警告"],
        start_time=time.time() - 30,
        end_time=time.time()
    )

    # 创建分析器并分析结果
    analyzer = TestAnalyzer()
    report = analyzer.analyze_test_results(config, stats)

    # 生成并显示报告
    print(analyzer.generate_report_text(report))

    # 保存报告
    analyzer.save_report(report)


if __name__ == "__main__":
    demo_analyzer()