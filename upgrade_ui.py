import os

def upgrade_dashboard():
    filepath = "flutter/lib/screens/dashboard/dashboard_screen.dart"
    if not os.path.exists(filepath):
        print("Dashboard file not found.")
        return

    with open(filepath, 'r') as f:
        content = f.read()

    # Ensure dart:ui is imported
    if "import 'dart:ui';" not in content:
        content = "import 'dart:ui';\n" + content

    # Replace mini player with a frosted glass player
    old_player = """  Widget _buildStickyMiniPlayer() {
    return Positioned(
      left: 20,
      right: 20,
      bottom: 15, // float slightly above the bottom tab bar line
      child: Container(
        height: 72,
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(20),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.08),
              blurRadius: 24,
              offset: const Offset(0, 8),
            ),
          ],
          border: Border.all(
            color: Colors.black.withOpacity(0.04),
            width: 1,
          ),
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(20),
          child: Stack(
            children: [
              Padding(
                padding: const EdgeInsets.all(12.0),
                child: Row(
                  children: [
                    Container(
                      width: 48,
                      height: 48,
                      decoration: const BoxDecoration(
                        gradient: LinearGradient(
                          colors: [Color(0xFF0F2027), Color(0xFF203A43)],
                          begin: Alignment.topLeft,
                          end: Alignment.bottomRight,
                        ),
                        shape: BoxShape.circle,
                      ),
                      child: const Center(
                        child: Icon(
                          CupertinoIcons.music_mic,
                          color: Colors.white,
                          size: 20,
                        ),
                      ),
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            "Cardiovascular System Terminology",
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: GoogleFonts.outfit(
                              fontSize: 14,
                              fontWeight: FontWeight.bold,
                              color: Colors.black,
                            ),
                          ),
                          Text(
                            "Lecture by Prof. Smirnov",
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: GoogleFonts.outfit(
                              fontSize: 11,
                              color: AppTheme.iosGray,
                            ),
                          ),
                        ],
                      ),
                    ),
                    Container(
                      width: 36,
                      height: 36,
                      decoration: BoxDecoration(
                        color: AppTheme.primaryColor.withOpacity(0.08),
                        shape: BoxShape.circle,
                      ),
                      child: const Center(
                        child: Icon(
                          CupertinoIcons.play_fill,
                          color: AppTheme.primaryColor,
                          size: 16,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              Positioned(
                bottom: 0,
                left: 0,
                right: 0,
                height: 3,
                child: FractionallySizedBox(
                  alignment: Alignment.centerLeft,
                  widthFactor: 0.35,
                  child: Container(
                    color: AppTheme.secondaryColor, // Coral Red progress line
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }"""

    new_player = """  Widget _buildStickyMiniPlayer() {
    return Positioned(
      left: 16,
      right: 16,
      bottom: 12,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(24),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 15, sigmaY: 15),
          child: Container(
            height: 74,
            decoration: BoxDecoration(
              color: Colors.white.withOpacity(0.85),
              borderRadius: BorderRadius.circular(24),
              border: Border.all(
                color: Colors.white.withOpacity(0.6),
                width: 1.5,
              ),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withOpacity(0.04),
                  blurRadius: 20,
                  offset: const Offset(0, 8),
                ),
              ],
            ),
            child: Stack(
              children: [
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  child: Row(
                    children: [
                      Container(
                        width: 50,
                        height: 50,
                        decoration: BoxDecoration(
                          gradient: const LinearGradient(
                            colors: [AppTheme.primaryColor, Color(0xFF0056B3)],
                            begin: Alignment.topLeft,
                            end: Alignment.bottomRight,
                          ),
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: const Center(
                          child: Icon(
                            CupertinoIcons.music_mic,
                            color: Colors.white,
                            size: 22,
                          ),
                        ),
                      ),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              "Cardiovascular System Terminology",
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: GoogleFonts.outfit(
                                fontSize: 14,
                                fontWeight: FontWeight.bold,
                                color: Colors.black87,
                              ),
                            ),
                            const SizedBox(height: 2),
                            Text(
                              "Lecture by Prof. Smirnov",
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: GoogleFonts.outfit(
                                fontSize: 11,
                                color: Colors.black45,
                                fontWeight: FontWeight.w500,
                              ),
                            ),
                          ],
                        ),
                      ),
                      Container(
                        width: 38,
                        height: 38,
                        decoration: BoxDecoration(
                          color: AppTheme.primaryColor.withOpacity(0.1),
                          shape: BoxShape.circle,
                        ),
                        child: const Center(
                          child: Icon(
                            CupertinoIcons.play_fill,
                            color: AppTheme.primaryColor,
                            size: 16,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                Positioned(
                  bottom: 0,
                  left: 0,
                  right: 0,
                  height: 3.5,
                  child: FractionallySizedBox(
                    alignment: Alignment.centerLeft,
                    widthFactor: 0.35,
                    child: Container(
                      color: AppTheme.secondaryColor,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }"""

    content = content.replace(old_player, new_player)
    
    with open(filepath, 'w') as f:
        f.write(content)
    print("Dashboard screen successfully upgraded to premium frosted glass UI!")

def upgrade_timeline():
    filepath = "flutter/lib/screens/dashboard/subject_topics_screen.dart"
    if not os.path.exists(filepath):
        print("Timeline file not found.")
        return

    with open(filepath, 'r') as f:
        content = f.read()

    if "import 'dart:ui';" not in content:
        content = "import 'dart:ui';\n" + content

    # Replace manual semester tabs button switcher with CupertinoSlidingSegmentedControl
    old_tabs = """  Widget _buildSemesterTabs() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
      child: Row(
        children: [
          _buildSemesterTabButton(0, "Semestr 1"),
          const SizedBox(width: 8),
          _buildSemesterTabButton(1, "Semestr 2"),
          const SizedBox(width: 8),
          _buildSemesterTabButton(2, "Exam Prep"),
        ],
      ),
    );
  }

  Widget _buildSemesterTabButton(int index, String label) {
    final isActive = _selectedSemesterTab == index;
    return Expanded(
      child: GestureDetector(
        onTap: () {
          setState(() {
            _selectedSemesterTab = index;
          });
        },
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 10),
          decoration: BoxDecoration(
            color: isActive ? AppTheme.primaryColor : Colors.grey.shade100,
            borderRadius: BorderRadius.circular(14),
          ),
          child: Center(
            child: Text(
              label,
              style: GoogleFonts.outfit(
                color: isActive ? Colors.white : Colors.black87,
                fontWeight: FontWeight.bold,
                fontSize: 13,
              ),
            ),
          ),
        ),
      ),
    );
  }"""

    new_tabs = """  Widget _buildSemesterTabs() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
      child: SizedBox(
        width: double.infinity,
        child: CupertinoSlidingSegmentedControl<int>(
          groupValue: _selectedSemesterTab,
          thumbColor: Colors.white,
          backgroundColor: Colors.grey.shade100,
          children: {
            0: Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Text("Semestr 1", style: GoogleFonts.outfit(fontWeight: FontWeight.bold, fontSize: 13)),
            ),
            1: Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Text("Semestr 2", style: GoogleFonts.outfit(fontWeight: FontWeight.bold, fontSize: 13)),
            ),
            2: Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Text("Exam Prep", style: GoogleFonts.outfit(fontWeight: FontWeight.bold, fontSize: 13)),
            ),
          },
          onValueChanged: (val) {
            if (val != null) {
              setState(() {
                _selectedSemesterTab = val;
              });
            }
          },
        ),
      ),
    );
  }"""

    content = content.replace(old_tabs, new_tabs)
    
    with open(filepath, 'w') as f:
        f.write(content)
    print("Timeline screen successfully upgraded to CupertinoSlidingSegmentedControl!")

def upgrade_leaderboard():
    filepath = "flutter/lib/screens/profile/leaderboard_screen.dart"
    if not os.path.exists(filepath):
        print("Leaderboard file not found.")
        return

    with open(filepath, 'r') as f:
        content = f.read()

    if "import 'dart:ui';" not in content:
        content = "import 'dart:ui';\n" + content

    old_tabs = """  Widget _buildLeaderboardTabs() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
      child: Container(
        padding: const EdgeInsets.all(4),
        decoration: BoxDecoration(
          color: Colors.grey.shade100,
          borderRadius: BorderRadius.circular(16),
        ),
        child: Row(
          children: [
            _buildTabButton(0, "Class"),
            _buildTabButton(1, "All"),
            _buildTabButton(2, "Friends"),
          ],
        ),
      ),
    );
  }

  Widget _buildTabButton(int index, String label) {
    final isActive = _selectedLeaderboardTab == index;
    return Expanded(
      child: GestureDetector(
        onTap: () {
          setState(() {
            _selectedLeaderboardTab = index;
          });
        },
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          padding: const EdgeInsets.symmetric(vertical: 10),
          decoration: BoxDecoration(
            color: isActive ? Colors.white : Colors.transparent,
            borderRadius: BorderRadius.circular(12),
            boxShadow: isActive 
                ? [
                    BoxShadow(
                      color: Colors.black.withOpacity(0.05),
                      blurRadius: 8,
                      offset: const Offset(0, 2),
                    )
                  ] 
                : [],
          ),
          child: Center(
            child: Text(
              label,
              style: GoogleFonts.outfit(
                color: isActive ? AppTheme.primaryColor : AppTheme.iosGray,
                fontWeight: FontWeight.bold,
                fontSize: 13,
              ),
            ),
          ),
        ),
      ),
    );
  }"""

    new_tabs = """  Widget _buildLeaderboardTabs() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
      child: SizedBox(
        width: double.infinity,
        child: CupertinoSlidingSegmentedControl<int>(
          groupValue: _selectedLeaderboardTab,
          thumbColor: Colors.white,
          backgroundColor: Colors.grey.shade100,
          children: {
            0: Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Text("Class", style: GoogleFonts.outfit(fontWeight: FontWeight.bold, fontSize: 13)),
            ),
            1: Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Text("All", style: GoogleFonts.outfit(fontWeight: FontWeight.bold, fontSize: 13)),
            ),
            2: Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Text("Friends", style: GoogleFonts.outfit(fontWeight: FontWeight.bold, fontSize: 13)),
            ),
          },
          onValueChanged: (val) {
            if (val != null) {
              setState(() {
                _selectedLeaderboardTab = val;
              });
            }
          },
        ),
      ),
    );
  }"""

    content = content.replace(old_tabs, new_tabs)
    
    with open(filepath, 'w') as f:
        f.write(content)
    print("Leaderboard screen successfully upgraded to CupertinoSlidingSegmentedControl!")

def upgrade_homework():
    filepath = "flutter/lib/screens/homework/homework_screen.dart"
    if not os.path.exists(filepath):
        print("Homework file not found.")
        return

    with open(filepath, 'r') as f:
        content = f.read()

    if "import 'dart:ui';" not in content:
        content = "import 'dart:ui';\n" + content

    old_tabs = """  Widget _buildHomeworkTabs() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
      child: Container(
        padding: const EdgeInsets.all(4),
        decoration: BoxDecoration(
          color: Colors.grey.shade100,
          borderRadius: BorderRadius.circular(16),
        ),
        child: Row(
          children: [
            _buildTabButton(0, "Student Portal"),
            _buildTabButton(1, "Teacher View"),
          ],
        ),
      ),
    );
  }

  Widget _buildTabButton(int index, String label) {
    final isActive = _selectedTab == index;
    return Expanded(
      child: GestureDetector(
        onTap: () {
          setState(() {
            _selectedTab = index;
          });
        },
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          padding: const EdgeInsets.symmetric(vertical: 10),
          decoration: BoxDecoration(
            color: isActive ? Colors.white : Colors.transparent,
            borderRadius: BorderRadius.circular(12),
            boxShadow: isActive 
                ? [
                    BoxShadow(
                      color: Colors.black.withOpacity(0.05),
                      blurRadius: 8,
                      offset: const Offset(0, 2),
                    )
                  ] 
                : [],
          ),
          child: Center(
            child: Text(
              label,
              style: GoogleFonts.outfit(
                color: isActive ? AppTheme.primaryColor : AppTheme.iosGray,
                fontWeight: FontWeight.bold,
                fontSize: 13,
              ),
            ),
          ),
        ),
      ),
    );
  }"""

    new_tabs = """  Widget _buildHomeworkTabs() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
      child: SizedBox(
        width: double.infinity,
        child: CupertinoSlidingSegmentedControl<int>(
          groupValue: _selectedTab,
          thumbColor: Colors.white,
          backgroundColor: Colors.grey.shade100,
          children: {
            0: Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Text("Student Portal", style: GoogleFonts.outfit(fontWeight: FontWeight.bold, fontSize: 13)),
            ),
            1: Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Text("Teacher View", style: GoogleFonts.outfit(fontWeight: FontWeight.bold, fontSize: 13)),
            ),
          },
          onValueChanged: (val) {
            if (val != null) {
              setState(() {
                _selectedTab = val;
              });
            }
          },
        ),
      ),
    );
  }"""

    content = content.replace(old_tabs, new_tabs)
    
    with open(filepath, 'w') as f:
        f.write(content)
    print("Homework screen successfully upgraded to CupertinoSlidingSegmentedControl!")

def main():
    upgrade_dashboard()
    upgrade_timeline()
    upgrade_leaderboard()
    upgrade_homework()

if __name__ == "__main__":
    main()
