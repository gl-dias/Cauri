# Backlog

Melhorias combinadas que ficaram para depois. Cada item diz o que muda e por que não
entrou ainda.

## Importação

- **Transferência de custódia entre corretoras.** Hoje a "Transferência" da B3 e o
  depósito ou saque de cripto entre carteiras próprias são ignorados com o motivo: a
  quantidade total não muda, mas a visão por corretora fica com a posição na corretora de
  origem. O certo é mover a posição para a corretora de destino (e, no saque de cripto,
  tirar a taxa de rede da quantidade).
- **Amortização e restituição de capital** (comum em FII de papel). Hoje a linha é
  ignorada com o motivo. O certo é reduzir o custo da posição pelo valor recebido, sem
  mexer na quantidade, e mostrar o valor na rentabilidade.
- **Passada de layout com export real da B3.** Os adaptadores de Negociação e
  Movimentação seguem o layout público da Área do Investidor e as fixtures são
  inventadas. Quando houver um export real, conferir nomes de colunas e os tipos de
  "Movimentação" que aparecem (só o layout; nenhum dado do arquivo vai para o repo).
- **Passada de layout com export real da Binance.** Mesmo caso: trades (Spot), Convert,
  P2P, depósitos e saques e o extrato de transações seguem o layout público, com fixtures
  inventadas. Conferir também o fuso do "Created Time" do P2P (hoje tratado como UTC, como os
  outros exports).
