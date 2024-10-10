#include <verilated.h>
#include <iostream>
#include <sstream>
#include "Vtop.h"

// One of the correct keys: 0x00E0102030604060

int main() {

  Verilated::debug(0);
  Verilated::randReset(2);
  Verilated::traceEverOn(true);
  
  
  std::cout << "  ∗               ∗        ∗               ∗          ∗     " << std::endl;
  std::cout << "         ∗                                                  " << std::endl;
  std::cout << "                                ∗                     ◦◦╽◦◦ " << std::endl;
  std::cout << "   ∗               ∗                      ∗          ◦◦ █  ◦" << std::endl;
  std::cout << "                                ∗                   ◦◦  █   " << std::endl;
  std::cout << "            ∗                         ∗         ∗  ◦◦   █   " << std::endl;
  std::cout << "     ∗              ∗    ◦╽◦◦                   ◦◦◦◦    █   " << std::endl;
  std::cout << "                       ◦◦ █ ◦◦◦         ◦◦╽◦◦◦◦◦◦       █   " << std::endl;
  std::cout << "                      ◦◦  █   ◦◦◦◦◦◦◦◦◦◦◦ █             █   " << std::endl;
  std::cout << "      ■■■■■■■■     ◦◦◦◦   █        ▛      █  ∗          █  ∗" << std::endl;
  std::cout << "     ▟        ▙ ◦◦◦       █  ∗     ▌      █         ∗   █   " << std::endl;
  std::cout << " ∗  ▟          ▙          █     ██████  ∗ █             █   " << std::endl;
  std::cout << "   ▟            ▙     ∗   █     █    █    █             █   " << std::endl;
  std::cout << "   ▛▀▀▀▀▀▀▀▀▀▀▀▀▜         █     ██████    █             █░░░" << std::endl;
  std::cout << "   ▌            ▐         █               █    ∗       ░░░░░" << std::endl;
  std::cout << "   ▌            ▐  ∗      █               █          ░░░░░▒▒" << std::endl;
  std::cout << "   ▌  ▛▀▀▀▜     ▐         █   ∗           █        ░░░░░▒░░░" << std::endl;
  std::cout << "∗  ▌  ▌   ▐     ▐      ∗  █          ∗   ░░░░░░░▓░░░░░░▒▒░░░" << std::endl;
  std::cout << "   ▌  ▌ ╾ ▐     ▐         █░░░░░      ░░░░▒░░░░▓░░░░░░░░░░░░" << std::endl;
  std::cout << "   ▌  ▌   ▐     ▐     ░░░░░▒▒▒░░░░░░░░░░░░░░░░░▒▒▒░░░░░░░▓▓▓" << std::endl;
  std::cout << "   ▙▄▄▙▄▄▄▟▄▄▄▄▄▟     ░░░░▒▒░░░░▓▓░░░░░░░░░▓░░░░░░░░░░░░░░░░" << std::endl;
  std::cout << "░░░░░░░░░░░▒▒▒░░░░▒░░░░░░░░░░░░░░░░░░░░▓▓░░░░░░░░░▓▓░░▒▒░░░░" << std::endl;
  std::cout << "░░▓░░▒░░░▓░░░░░░░░░░░░░░░░░▒░▓░░░▒░░░░▓░░░░░▒░░░░▓▓░▒▒░░░░░░" << std::endl;
  std::cout << "░▓▓░░▒░░░░░░▒░░░░░░░░░░░░░░░▓▓▓░░░▒░░░░░░░░░▒▒░▒░░░░░░░░▒░░░" << std::endl;
  std::cout << "░░░░░░░▒░░░░░░░░▓▓▓░░░░▒▒░░▒░░░░░░▒▓▓░░▒▒░░░░░░▓░░▓░░░░▓▒░░░" << std::endl;
  std::cout << "░░░▒░░░▓░░░░░▒░░░░░░▒▓░░░░░░░░░░░░░▓░░░░░░░▓░░▓░▓░░░░░░▓░░░░" << std::endl;
  std::cout << "░░░░░░▓▓░░░▒▒▒░░░░░░░▓▓▓▓▓░░░░▒░░░░░▒░░░░░░░░░░▒░░░░▒░░░░░░░" << std::endl;
  std::cout << "░░░░▓░▒▒▒░░░░░░░░░░▒░░░░░░░░░░▓▓▓▒░░░░░░░░░▒░░░░▓░░░░░▓▓░░▒░" << std::endl;
  std::cout << "░░▓▓░░░░░░░▓░░▒░░░░░░░░░▒▒▒▒▒░░░░░░░░▒░▒▒░░░░░▓▓░░░░▓▓░░░░░░" << std::endl;

  std::cout << std::endl << std::endl;
  
  std::cout << "               ╔═════════════════════════════╗" << std::endl;
  std::cout << "               ║ > Welcome to SkiOS v1.0.0   ║" << std::endl;
  std::cout << "               ║                             ║" << std::endl;
  std::cout << "               ║ > Please provide the        ║" << std::endl;
  std::cout << "               ║   master key to start       ║" << std::endl;
  std::cout << "               ║   the ski lift              ║" << std::endl;
  std::cout << "               ║                             ║" << std::endl;
  std::cout << "               ║ (format 0x1234567812345678) ║" << std::endl;
  std::cout << "               ║                             ║" << std::endl;
  std::cout << "               ╚═════════════════════════════╝" << std::endl << std::endl;
  
  std::cout << "                    Please input your key" << std::endl;
  std::cout << "                    >";

  
  std::string line;
  std::getline(std::cin, line);
  
  unsigned long int input = 0;
  
  try {
    input = std::stoul(line, nullptr, 16);
  }
  catch (...) {
    std::cout << " Wrong input!" << std::endl << std::endl;
  }

  Vtop* top = new Vtop;
  top->key = input;
  top->eval();
  top->final();
  
  if (top->lock == 1) std::cout << " gctf{V3r1log_ISnT_SO_H4rd_4fTer_4ll_!1!}" << std::endl << std::endl;
  else std::cout << " Wrong key!" << std::endl << std::endl;
  
  delete top;
  top = NULL;
  return 0;
}
