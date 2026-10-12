# Classificador de IVA — versão organizada

Esta versão transforma a página HTML em uma aplicação Python/FastAPI. A tela mantém a análise automática ao selecionar arquivos e aceita XML e PDF juntos.

## 1. Como iniciar no Windows

1. Extraia o ZIP para uma pasta fácil, por exemplo `C:\\ClassificadorIVA`.
2. Instale Python 3.11 ou mais recente, se ainda não tiver. Durante a instalação, marque **Add Python to PATH**.
3. Dê dois cliques em `iniciar_windows.bat`.
4. Na primeira execução, o arquivo instala as bibliotecas necessárias.
5. Quando aparecer a mensagem de que o servidor está iniciado, abra: **http://localhost:8000/nfe-iva-classifier-dinamico.html**
6. Para encerrar, volte à janela preta do terminal e pressione `Ctrl+C`.

Se já tiver um servidor antigo usando a porta 8000, pare-o antes de iniciar esta versão.

## 2. Onde mudar os códigos

- `regras/ivas.csv`: tabela ativa de mapeamentos. Abra no Excel (delimitador ponto e vírgula) ou no Bloco de Notas para editar origens, destinos e descrições. Não apague a primeira linha de cabeçalhos. A aplicação lê este arquivo a cada análise.
- `regras/configuracao.json`: algumas opções gerais, como limite de itens enviados para revisão do Gemini.
- `main.py`: regras de leitura e classificação. Por enquanto, não precisa editar este arquivo para alterar os mapeamentos simples da tabela.

Após salvar `regras/ivas.csv`, a aplicação lê a tabela novamente na próxima análise; não precisa reiniciar o servidor. Faça uma cópia de segurança antes de editar.

## 3. Chave Google Gemini (opcional)

Na tela, cole sua chave no campo **Chave da API Google Gemini**. Ao selecionar um arquivo ou alterar a chave, a análise é executada novamente. Também pode configurar a chave no arquivo `.env`:

1. Faça uma cópia de `.env.example` com o nome `.env`.
2. Abra `.env` no Bloco de Notas.
3. Preencha `GEMINI_API_KEY=sua_chave_aqui`.
4. Salve.

O `.env` não deve ser compartilhado nem enviado para outras pessoas. A chave digitada na tela é enviada ao seu próprio servidor local e não é gravada pelo aplicativo. Se usar Gemini, os dados fiscais estruturados dos itens são enviados à API do Google para revisão.

O Gemini só pode alterar um resultado quando propõe uma origem reconhecida, um código de destino permitido pela tabela para aquela condição de IBS/CBS, uma justificativa e confiança declarada de pelo menos 0,85. Se não passar na validação, o resultado local é mantido. A confiança é informada pelo próprio modelo e não garante acerto fiscal.

## 4. Limitações importantes desta versão

- A matriz de serviços J1/J2/J3/J4 é aplicada deterministicamente conforme a regra definida pelo usuário e não é sobrescrita pelo Gemini.
- O arquivo `IVAS.txt` recebido tem 26 linhas e não contém a tabela completa de todas as famílias (por exemplo, Imobilizado e Frete). A aplicação sinaliza esses casos em vez de inventar regras.
- O cálculo de origem de materiais ainda usa heurísticas sobre os campos do XML; confirme cada resultado antes de usar no SAP. Não faça lançamentos fiscais só com base nesta versão.
- Para PDF de material sem XML estruturado, não há garantia de classificação por item.
- A API Gemini depende de chave válida, acesso à internet, cota e disponibilidade do modelo configurado.

## 5. Testes

Com o ambiente virtual ativado, execute:

```bat
python -m unittest discover -s tests -v
```
