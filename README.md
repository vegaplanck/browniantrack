# BrownianTrack

Aplicativo desktop multiplataforma para acompanhar partículas em vídeos e
analisar movimento browniano usando [trackpy](https://github.com/soft-matter/trackpy).

## Requisitos

- Conda
- O ambiente `fisexpvi`, com PySide6 (Qt 6), `trackpy` e `pims`

## Instalação e execução

Ative o ambiente já configurado:

```bash
conda activate fisexpvi
```

Na pasta do projeto, instale o pacote em modo editável e inicie a aplicação:

```bash
python -m pip install -e .
python -m browniantrack
```

No Windows e no macOS, os mesmos comandos funcionam em um terminal com o Conda
configurado. A interface é local e não requer servidor.

## Versões standalone (Windows e Linux)

Os executáveis são construídos nativamente para cada sistema; o arquivo de um
sistema não funciona no outro. Para gerar o pacote no sistema atual, instale os
requisitos de build e execute:

```bash
python -m pip install ".[build]"
python build_standalone.py
```

O arquivo compactado fica em `dist/`: `.zip` no Windows e `.tar.gz` no Linux.
Extraia a pasta inteira e execute `BrownianTrack.exe` (Windows) ou
`BrownianTrack` (Linux). O Linux deve ter uma distribuição relativamente
recente; vídeos e resultados podem ser abertos/salvos em qualquer pasta.

Para gerar os pacotes pelo GitHub Actions:

1. Envie o projeto ao GitHub e abra a página do repositório.
2. Selecione **Actions** e, se solicitado, confirme a habilitação das actions.
3. Na lista à esquerda, clique em **Build standalone applications**.
4. Clique em **Run workflow**, mantenha a branch `main` selecionada e confirme
   em **Run workflow**.
5. Quando os dois jobs terminarem com sucesso, abra a execução e baixe em
   **Artifacts** o pacote `BrownianTrack-windows-x86_64` (Windows) e/ou
   `BrownianTrack-linux-x86_64` (Linux). O GitHub mantém esses downloads por
   30 dias.

Cada pacote é construído num runner nativo do respectivo sistema, sem
compilação cruzada. Também é possível iniciar os dois builds ao enviar ao
GitHub uma tag cujo nome comece por `v`, por exemplo `v0.1.0`.

## Uso

Use **Modo escuro** na barra superior para alternar a aparência da interface sem
reiniciar o aplicativo.

1. Abra um vídeo pelo menu **Arquivo → Abrir…** ou use `Ctrl+O` (`Cmd+O` no
   macOS). O PIMS abre o arquivo para validar a leitura e exibe as dimensões e
   a quantidade de quadros.
2. Use **Reproduzir/Pausar** e a barra de posição para acompanhar o vídeo.
   O indicador da reprodução também acompanha a unidade selecionada no
   intervalo: mostra o quadro atual ou o tempo decorrido em segundos.
3. Digite o diâmetro e a massa mínima e clique em **Aplicar** ao lado do campo.
   A edição dos campos não aciona a detecção; os valores só são validados e
   usados após clicar em **Aplicar**. Durante a reprodução, o ajuste aplicado
   vale para os quadros seguintes.
4. Ative **Círculos vermelhos** para desenhar as detecções com `trackpy.annotate`.
   Ative **Exibir em escala de cinza** para visualizar a conversão do PIMS.
   A detecção do trackpy sempre usa tons de cinza, pois o localizador trabalha
   com imagens 2D; a opção de exibição não altera esse processamento.
5. Em **Intervalo de análise**, escolha **Quadros** ou **Segundos** e informe
   o início e o fim. A numeração dos quadros começa em 1 e os dois limites são
   inclusivos; valores em segundos são convertidos para o quadro mais próximo
   usando a taxa de quadros do vídeo.
   Use **Analisar intervalo** para rastrear apenas esse trecho ou **Analisar
   vídeo todo** para rastrear todos os quadros, sem depender do intervalo.
   Durante o processamento, a barra de progresso mostra o quadro atual e o
   percentual concluído.
6. Após uma análise que detecte partículas, use **Dados de Tracking** para
   visualizar as localizações e trajetórias em uma tabela; **Salvar CSV…**
   grava os dados exibidos. **Visualizar gráfico** abre as trajetórias geradas
   por `trackpy.plot_traj`; use o botão de salvar da barra de ferramentas do
   Matplotlib para guardar o gráfico como imagem. O CSV conserva os números de
   quadro originais do vídeo, começando em 0.
7. Preencha o raio hidrodinâmico (nm) e a temperatura do experimento (°C), e
   use **Calcular Grandezas** para exibir um resumo e a curva MSD em tabelas.
   O botão **Salvar planilha…** na janela das tabelas salva um arquivo Excel
   (.xlsx) com as abas **Resumo** e **Curva MSD**. A escala espacial em
   µm/pixel é opcional: sem ela, MSD e difusão são reportados em unidades de
   pixel e a viscosidade física não é inferida. O relatório identifica
   explicitamente \(k_B\) e \(N_A\) como constantes tabeladas.

   **Dados de Tracking**, **Visualizar gráfico** e **Calcular Grandezas** só
   ficam habilitados após a análise de um intervalo com partículas detectadas.

Os parâmetros de detecção dependem da escala e do contraste do vídeo. O
diâmetro deve ser um inteiro ímpar, em pixels.

Os tempos dos quadros são obtidos dos timestamps do vídeo quando disponíveis.
O expoente anômalo é ajustado em escala logarítmica; a viscosidade só é inferida
pela relação simples de Stokes–Einstein quando \(\alpha\) está próximo de 1.
O regime é classificado como subdifusivo (\(\alpha < 0{,}8\)), aproximadamente
normal (\(0{,}8 \leq \alpha \leq 1{,}2\)) ou superdifusivo (\(\alpha > 1{,}2\)).
O ajuste utiliza lags de até um quarto do intervalo analisado.

## Estrutura

```text
src/browniantrack/
├── __main__.py           # Entrada: python -m browniantrack
├── app.py                # Inicialização da aplicação
├── core/
│   ├── tracking.py       # Análise completa e pipeline trackpy
│   └── video_preview.py  # Pré-visualização e detecção por quadro
└── ui/
    └── main_window.py    # Interface desktop PySide6/Qt 6
tests/
└── test_tracking.py      # Testes dos parâmetros de análise
```

## Testes

```bash
python -m unittest discover -s tests
```
