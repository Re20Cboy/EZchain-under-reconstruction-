案例1（简单正常交易，有checkpoint）：
创世块：alice是目标value的首位所有者（从GOD处获得）
区块8：alice进行其他交易（非目标value）
区块15：bob从alice处接收目标value（alice->bob交易）
区块16：bob进行其他交易（非目标value）
区块25：bob进行其他交易（非目标value）
区块27：charlie从bob处接收目标value（bob->charlie交易）
区块55：charlie进行其他交易（非目标value）
区块56：dave从charlie处接收目标value（charlie->dave交易）
区块58：bob从dave处接收目标value（dave->bob交易）
期望结果：dave->bob交易会触发bob的checkpoint(因为bob曾拥有过目标value)，从区块27开始验证。
--------------
案例2（简单正常交易，无checkpoint）：
创世块：alice是目标value的首位所有者（从GOD处获得）
区块8：alice进行其他交易（非目标value）
区块15：bob从alice处接收目标value（alice->bob交易）
区块16：bob进行其他交易（非目标value）
区块25：bob进行其他交易（非目标value）
区块27：charlie从bob处接收目标value（bob->charlie交易）
区块55：charlie进行其他交易（非目标value）
区块56：dave从charlie处接收目标value（charlie->dave交易）
区块58：eve从dave处接收目标value（dave->eve交易）
期望结果：dave->eve交易,eve会从头开始验证
--------------
案例3（简单双花交易，有checkpoint）：
创世块：alice是目标value的首位所有者（从GOD处获得）
区块8：alice进行其他交易（非目标value）
区块15：bob从alice处接收目标value（alice->bob交易）
区块16：bob进行其他交易（非目标value）
区块25：bob进行其他交易（非目标value）
区块27：charlie从bob处接收目标value（bob->charlie交易）
区块55：charlie进行其他交易（非目标value）
区块56：dave从charlie处接收目标value（charlie->dave交易）
区块57：dave是恶意的，将目标value转移给了其同伙x
区块58：bob从dave处接收目标value（dave->bob交易）
期望结果：dave->bob交易会触发bob的checkpoint(因为bob曾拥有过目标value)，从区块27开始验证，并且bob会发现dave在区块57对目标value进行了双花。
--------------
案例4（简单双花交易，无checkpoint）：
创世块：alice是目标value的首位所有者（从GOD处获得）
区块8：alice进行其他交易（非目标value）
区块15：bob从alice处接收目标value（alice->bob交易）
区块16：bob进行其他交易（非目标value）
区块25：bob进行其他交易（非目标value）
区块27：charlie从bob处接收目标value（bob->charlie交易）
区块55：charlie进行其他交易（非目标value）
区块56：dave从charlie处接收目标value（charlie->dave交易）
区块57：dave是恶意的，将目标value转移给了其同伙x
区块58：eve从dave处接收目标value（dave->eve交易）
期望结果：dave->eve交易，eve会从头开始验证，并且eve会发现dave在区块57对目标value进行了双花。
--------------
案例5（组合正常交易，有checkpoint）：
目标value_1：
创世块：alice是目标value_1的首位所有者（从GOD处获得）
区块8：alice进行其他交易（非目标value_1）
区块15：bob从alice处接收目标value_1（alice->bob交易）
区块16：bob进行其他交易（非目标value_1）
区块25：bob进行其他交易（非目标value_1）
区块27：charlie从bob处接收目标value_1（bob->charlie交易）
区块55：charlie进行其他交易（非目标value_1）
区块56：dave从charlie处接收目标value_1（charlie->dave交易）

目标value_2：
创世块：zhao是目标value_2的首位所有者（从GOD处获得）
区块3：zhao进行其他交易（非目标value_2）
区块5：qian从zhao处接收目标value_2（zhao->qian交易）
区块17：qian进行其他交易（非目标value_2）
区块38：sun从qian处接收目标value_2（qian->sun交易）
区块39：dave从sun处接收目标value_2（sun->dave交易）

区块58：qian从dave处接收目标value_1+目标value_2（dave->qian交易,这是一笔组合支付）
期望结果：dave->qian交易会触发qian的checkpoint(因为qian曾拥有过目标value_2)，从区块38开始验证目标value_2，目标value_1从头验证。
--------------
案例6（组合正常交易，无checkpoint）：
创世块：alice是目标value_1的首位所有者（从GOD处获得）
区块8：alice进行其他交易（非目标value_1）
区块15：bob从alice处接收目标value_1（alice->bob交易）
区块16：bob进行其他交易（非目标value_1）
区块25：bob进行其他交易（非目标value_1）
区块27：charlie从bob处接收目标value_1（bob->charlie交易）
区块55：charlie进行其他交易（非目标value_1）
区块56：dave从charlie处接收目标value_1（charlie->dave交易）

创世块：zhao是目标value_2的首位所有者（从GOD处获得）
区块3：zhao进行其他交易（非目标value_2）
区块5：qian从zhao处接收目标value_2（zhao->qian交易）
区块17：qian进行其他交易（非目标value_2）
区块38：sun从qian处接收目标value_2（qian->sun交易）
区块39：dave从sun处接收目标value_2（sun->dave交易）

区块58：eve从dave处接收目标value_1+目标value_2（dave->eve交易,这是一笔组合支付）
期望结果：dave->eve交易,eve会从头开始验证两个目标value的合法性和正确性。
--------------
案例7（组合双花交易，有checkpoint）：
创世块：alice是目标value_1的首位所有者（从GOD处获得）
区块8：alice进行其他交易（非目标value_1）
区块15：bob从alice处接收目标value_1（alice->bob交易）
区块16：bob进行其他交易（非目标value_1）
区块25：bob进行其他交易（非目标value_1）
区块27：charlie从bob处接收目标value_1（bob->charlie交易）
区块55：charlie进行其他交易（非目标value_1）
区块56：dave从charlie处接收目标value_1（charlie->dave交易）

创世块：zhao是目标value_2的首位所有者（从GOD处获得）
区块3：zhao进行其他交易（非目标value_2）
区块5：qian从zhao处接收目标value_2（zhao->qian交易）
区块17：qian进行其他交易（非目标value_2）
区块38：sun从qian处接收目标value_2（qian->sun交易）
区块39：dave从sun处接收目标value_2（sun->dave交易）
区块46：dave是恶意的，将目标value_2转移给了其同伙x

区块58：sun从dave处接收目标value_1+目标value_2（dave->sun交易,这是一笔组合支付）

期望结果：dave->sun交易会触发sun的checkpoint(因为sun曾拥有过目标value_2)，从区块39开始验证目标value_2，会发现dave在区块46对目标value_2进行了双花。
--------------
案例8（组合双花交易，无checkpoint）：

创世块：alice是目标value_1的首位所有者（从GOD处获得）
区块8：alice进行其他交易（非目标value_1）
区块15：bob从alice处接收目标value_1（alice->bob交易）
区块16：bob进行其他交易（非目标value_1）
区块25：bob进行其他交易（非目标value_1）
区块27：charlie从bob处接收目标value_1（bob->charlie交易）
区块55：charlie进行其他交易（非目标value_1）
区块56：dave从charlie处接收目标value_1（charlie->dave交易）

创世块：zhao是目标value_2的首位所有者（从GOD处获得）
区块3：zhao进行其他交易（非目标value_2）
区块5：qian从zhao处接收目标value_2（zhao->qian交易）
区块17：qian进行其他交易（非目标value_2）
区块38：sun从qian处接收目标value_2（qian->sun交易）
区块39：dave从sun处接收目标value_2（sun->dave交易）
区块46：dave是恶意的，将目标value_2转移给了其同伙x

区块58：eve从dave处接收目标value_1+目标value_2（dave->eve交易,这是一笔组合支付）

期望结果：dave->eve交易,eve会从头开始验证，会发现dave在区块46对目标value_2进行了双花。

==============
## 高级复杂测试案例

案例9（复杂多级checkpoint验证）：
目标value：价值100单位的数字资产
创世块：alice获得目标value（从GOD处）
区块10：alice->bob（转移100单位）
区块20：bob->charlie（转移100单位）
区块25：charlie创建checkpoint
区块30：charlie->dave（转移50单位，剩余50单位）
区块35：charlie->eve（转移剩余50单位）
区块40：eve创建checkpoint
区块45：eve->frank（转移100单位，合并了之前收到的50单位）
区块50：frank创建checkpoint
区块55：frank->grace（转移100单位）
期望结果：每个checkpoint都能正确验证之前的历史，最终验证成功。

案例10（跨epoch多次转移验证）：
目标value：价值200单位的数字资产
创世块：alice获得目标value（从GOD处）
区块15：alice->bob（转移200单位）
区块30：bob->charlie（转移150单位，剩余50单位）
区块32：bob->dave（转移剩余50单位）
区块45：charlie->eve（转移150单位）
区块47：dave->frank（转移50单位）
区块60：eve->grace（转移150单位）
区块62：frank->henry（转移50单位）
区块75：grace->ivy（转移100单位，剩余50单位）
区块77：grace->jack（转移剩余50单位）
期望结果：系统能正确处理同一value的多次分割和合并，验证所有交易的合法性。

案例11（恶意攻击案例 - 隐藏双花）：
目标value：价值300单位的数字资产
创世块：alice获得目标value（从GOD处）
区块20：alice->bob（转移300单位）
区块25：alice恶意尝试将同一value转移给malicious_user（双花尝试1）
区块30：bob->charlie（转移300单位）
区块35：bob恶意尝试将同一value转移给attacker（双花尝试2）
区块40：charlie->dave（转移300单位）
区块45：charlie恶意尝试将同一value转移给hacker（双花尝试3）
区块50：dave->eve（转移300单位）
期望结果：系统应该检测出所有双花尝试，拒绝恶意交易。

案例12（边界条件测试 - 极短间隔）：
目标value：价值1单位的数字资产
创世块：alice获得目标value（从GOD处）
区块1：alice->bob（转移1单位）
区块2：bob->charlie（转移1单位）
区块3：charlie->dave（转移1单位）
区块4：dave->eve（转移1单位）
区块5：eve->frank（转移1单位）
期望结果：即使是极短间隔的交易，系统也能正确验证。

案例13（大规模交易压力测试）：
目标value：价值1000单位的数字资产
创世块：alice获得目标value（从GOD处）
区块10-100：alice进行100笔不同的其他交易（非目标value）
区块105：alice->bob（转移1000单位）
区块110-200：bob进行90笔不同的其他交易（非目标value）
区块205：bob->charlie（转移1000单位）
区块210-300：charlie进行80笔不同的其他交易（非目标value）
区块305：charlie->dave（转移1000单位）
区块310-400：dave进行70笔不同的其他交易（非目标value）
区块405：dave->eve（转移1000单位）
期望结果：系统在大量交易背景下仍能准确验证目标value的转移。

案例14（复杂分割合并验证）：
目标value：价值1000单位的数字资产
创世块：alice获得目标value（从GOD处）
区块20：alice->bob（转移1000单位）
区块25：bob->charlie（转移300单位）
区块26：bob->dave（转移300单位）
区块27：bob->eve（转移400单位）
区块35：charlie->frank（转移300单位）
区块36：dave->grace（转移150单位，剩余150单位）
区块37：eve->henry（转移200单位，剩余200单位）
区块38：dave->ivy（转移剩余150单位）
区块39：eve->jack（转移剩余200单位）
区块45：frank->kyle（转移300单位）
区块46：grace->liam（转移150单位）
区块47：henry->mia（转移200单位）
区块48：ivy->noah（转移150单位）
区块49：jack->olivia（转移200单位）
区块55：所有5个用户将各自的value转移到最终接收者sophia
期望结果：系统能正确处理复杂的分割和合并操作，验证所有交易的合法性。

案例15（并发交易冲突测试）：
目标value：价值500单位的数字资产
创世块：alice获得目标value（从GOD处）
区块20：alice->bob（转移500单位）
区块25：bob尝试将同一value同时转移给charlie和dave（并发冲突）
区块30：系统应该检测出并发冲突，只允许其中一个交易成功
区块35：成功的接收者->eve（转移500单位）
期望结果：系统能正确处理并发交易冲突，确保同一value在同一时间只能被转移一次。

案例16（长期持有验证）：
目标value：价值100单位的数字资产
创世块：alice获得目标value（从GOD处）
区块100：alice->bob（转移100单位）
区块200：bob->charlie（转移100单位）
区块300：charlie->dave（转移100单位）
区块400：dave->eve（转移100单位）
区块500：eve->frank（转移100单位）
期望结果：系统能正确处理长期持有的value，即使中间有很长的无交易期。

案例17（混合资产交易验证）：
目标value_1：价值100单位的数字资产A
目标value_2：价值200单位的数字资产B
创世块：alice获得value_1，bob获得value_2
区块20：alice->charlie（转移value_1）
区块25：bob->charlie（转移value_2）
区块30：charlie将value_1+value_2一起转移给dave（混合交易）
区块35：dave->eve（转移混合资产）
期望结果：系统能正确验证混合资产交易的合法性。

案例18（回滚攻击测试）：
目标value：价值300单位的数字资产
创世块：alice获得目标value（从GOD处）
区块20：alice->bob（转移300单位）
区块25：bob->charlie（转移300单位）
区块30：恶意攻击者尝试回滚到区块20的状态，并将value转移给attacker
区块35：charlie->dave（转移300单位）
期望结果：系统应该检测出回滚攻击，拒绝非法的状态变更。

案例19（多路径并行验证）：
目标value：价值400单位的数字资产
创世块：alice获得目标value（从GOD处）
区块20：alice分割value为4份，每份100单位
区块21：alice->bob（转移第1份）
区块22：alice->charlie（转移第2份）
区块23：alice->dave（转移第3份）
区块24：alice->eve（转移第4份）
区块30：所有4个用户将各自的100单位转移给最终接收者frank
期望结果：系统能正确并行验证多条路径，最终成功合并。

案例20（极限压力测试）：
目标value：价值10000单位的数字资产
创世块：alice获得目标value（从GOD处）
区块10-1000：系统中有10000笔不同的交易
其中目标value的交易随机分布在：
区块100：alice->bob（转移10000单位）
区块200：bob->charlie（转移10000单位）
区块300：charlie->dave（转移10000单位）
区块400：dave->eve（转移10000单位）
区块500：eve->frank（转移10000单位）
期望结果：在极大量交易的背景下，系统仍能准确识别和验证目标value的交易路径。


