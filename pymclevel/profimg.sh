python gprof2dot.py -f pstats $1 > /tmp/mcedit.dot && dot -Tpng /tmp/mcedit.dot -o $0.png && start $0.png
