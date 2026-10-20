# Capstone graph benchmark (Direction 1)

M1 capstone: how well do open-source vision-language models turn an image of a graph into Cypher / JSON?

## Run
pip install -r requirements.txt
python src/generate_graphs.py --selftest
python src/generate_graphs.py --out data/samples --pilot
python src/load_to_neo4j.py --samples data/samples --reset

## Structure
src/ code, docs/ specification and reports, notes/ reading notes, results/ result tables, data/ generated data (not in Git)
