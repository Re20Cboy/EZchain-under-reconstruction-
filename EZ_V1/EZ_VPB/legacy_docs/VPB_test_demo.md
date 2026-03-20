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
区块57：dave是恶意的，将目标value转移给了其同伙x（dave会隐藏dave->x交易在目标value的proofs和block index list中的对应片段）
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
区块57：dave是恶意的，将目标value转移给了其同伙x（dave会隐藏dave->x交易在目标value的proofs和block index list中的对应片段）
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
区块46：dave是恶意的，将目标value_2转移给了其同伙x（dave会隐藏dave->x交易在目标value的proofs和block index list中的对应片段）

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
区块46：dave是恶意的，将目标value_2转移给了其同伙x（dave会隐藏dave->x交易在目标value的proofs和block index list中的对应片段）

区块58：eve从dave处接收目标value_1+目标value_2（dave->eve交易,这是一笔组合支付）

期望结果：dave->eve交易,eve会从头开始验证，会发现dave在区块46对目标value_2进行了双花。
