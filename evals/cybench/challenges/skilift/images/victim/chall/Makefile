
verilator:
	verilator --cc --exe --build -j 0 -Wall sim_main.cpp top.v

run:
	./obj_dir/Vtop

formal:
	sby formal.sby cover -f

.PHONY: verilator formal run

