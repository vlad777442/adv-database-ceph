PAPER_DIR = paper
MAIN = main
LATEX = pdflatex
BIBTEX = bibtex

.PHONY: all clean

all: $(PAPER_DIR)/$(MAIN).pdf

$(PAPER_DIR)/$(MAIN).pdf: $(PAPER_DIR)/$(MAIN).tex $(PAPER_DIR)/tables.tex
	cd $(PAPER_DIR) && $(LATEX) $(MAIN) && $(LATEX) $(MAIN)

clean:
	cd $(PAPER_DIR) && rm -f *.aux *.bbl *.blg *.log *.out *.pdf *.fls *.fdb_latexmk *.synctex.gz
