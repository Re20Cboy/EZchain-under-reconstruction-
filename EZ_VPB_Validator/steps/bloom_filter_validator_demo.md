布隆过滤器验证核心思想是：根据main_chain_info信息（这是一定正确的信息），
来判断外部提供的输入vpb_slice中的block_index_slice中的相应数据是否和布隆过滤器中的记录一一对应。

场景1：
假设目标value的真实的所有权转移历史如下（被记录进main_chain_info）：
创世块（区块0）：alice是目标value的首位所有者（从GOD处获得）
区块8：alice作为sender提交交易（非目标value）
区块15：bob从alice处接收目标value（alice->bob交易）
区块16：bob作为sender提交交易（非目标value）
区块25：bob作为sender提交交易（非目标value）
区块27：charlie从bob处接收目标value（bob->charlie交易）
区块55：charlie作为sender提交交易（非目标value）
区块56：dave从charlie处接收目标value（charlie->dave交易）
区块58（当前待验证交易）：eve从dave处接收目标value（dave->eve交易）

验证者提供的vpb_slice.block_index_slice.index_lst是：[0,8,15,16,25,27,55,56,58]。
提供的vpb_slice.block_index_slice.owner是：[(0, alice), (15, bob), (27, charlie), (56, dave), (58, eve)]。
那么我们可提取出各个owner的epochs为：
alice: （0，14），表示alice在区块0到区块14期间是目标value的owner，且alice在自己的epoch内作为sender提交交易(包括非目标value交易)的区块高度是：[8]
bob:   （15，26），表示bob在区块15到区块26期间是目标value的owner，且bob在自己的epoch内作为sender提交交易(包括非目标value交易)的区块高度是：[16, 25]
charlie:（27，54），表示charlie在区块27到区块54期间是目标value的owner，且charlie在自己的epoch内作为sender提交交易(包括非目标value交易)的区块高度是：[55]
dave:  （56，57），表示dave在区块56到区块57期间是目标value的owner，且dave在自己的epoch内作为sender提交交易(包括非目标value交易)的区块高度是：[]（为空，因为dave没有作为sender的交易）
eve:   （58，当前区块高度），表示eve在区块58获得目标value。

现在需要验证的就是根据这些epochs，去main_chain_info中的布隆过滤器中检查，
看这些owner在其对应的epoch期间，是否在布隆过滤器中被正确记录。例如：
对于bob的epoch：（15，26）的验证：1）需要检查main_chain_info中区块15到区块26的布隆过滤器，输入bob的地址，检查是否为[16,25]?
2）逻辑上，bob一定在区块27的布隆过滤器中被记录，因为bob在区块27作为sender提交了目标value的交易。因此，验证时也需要检查区块27的布隆过滤器，输入bob的地址，检查是否为[27]?
依照上述逻辑对所有epoch都进行相应检查（最后一个eve的epoch无需验证），即可完成布隆过滤器验证。

由于main_chain_info中的布隆过滤器一定会记录所有在本块中提交交易的sender的地址，因此，
如果攻击者试图隐藏某些恶意区块（例如包含双花交易的区块，攻击者在这些区块中必是sender提交交易，且被记录在布隆过滤器中），
通过检查这些区块的布隆过滤器，可以检测到攻击者隐藏恶意区块的行为。